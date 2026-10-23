"""
Thread-safe print queue with cancel support.

Jobs are added to a queue and processed one at a time by a background worker.
Each job gets a unique ID so it can be listed or cancelled before it prints.
"""

import logging
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from parser import PrintRequest
from printer import print_label, render_label, print_double_rows
from batch_manager import get_next_batch_number
from logger import log_print
from settings_manager import get_roll_type

_log = logging.getLogger(__name__)


@dataclass
class QueueJob:
    id: str
    req: PrintRequest
    batch_no: str
    username: str
    source: str  # "ui" or "telegram"
    status: str = "queued"  # queued | printing | done | failed | cancelled | dismissed
    created_at: str = ""
    error: Optional[str] = None
    finished_at: str = ""      # HH:MM:SS the job reached done / failed / cancelled
    finished_ts: float = 0.0   # same moment as epoch seconds, for ordering
    test: bool = False         # a calibration label: no batch number, not logged

    def finish(self, status: str):
        self.status = status
        self.finished_at = datetime.now().strftime("%H:%M:%S")
        self.finished_ts = time.time()

    def to_dict(self):
        return {
            "id": self.id,
            "product": self.req.product,
            "weight": self.req.weight,
            "quantity": self.req.quantity,
            "packed_on": self.req.packed_on,
            "best_before": self.req.best_before,
            "hotel": self.req.hotel,
            "label_type": self.req.label_type,
            "roll_type": self.req.roll_type,
            "batch_no": self.batch_no,
            "username": self.username,
            "source": self.source,
            "status": self.status,
            "created_at": self.created_at,
            "error": self.error,
            "finished_at": self.finished_at,
            "finished_ts": self.finished_ts,
            "test": self.test,
        }


class PrintQueue:
    def __init__(self):
        self._lock = threading.Lock()
        # OrderedDict preserves insertion order — oldest first
        self._jobs: OrderedDict[str, QueueJob] = OrderedDict()
        self._worker = threading.Thread(target=self._process_loop, daemon=True)
        self._worker.start()

    @staticmethod
    def _fix_roll(reqs):
        """
        Give every request without a label type the default one, now. A job
        prints in the size it was queued as, even if the default changes
        while it waits.
        """
        default = None
        for req in reqs:
            if not req.roll_type:
                default = default or get_roll_type()
                req.roll_type = default

    def add(self, req: PrintRequest, username: str, source: str = "ui") -> QueueJob:
        """Add a print request to the queue. Returns the created job."""
        self._fix_roll([req])
        batch_no = get_next_batch_number() if req.label_type == "product" else ""
        job = QueueJob(
            id=uuid.uuid4().hex[:8],
            req=req,
            batch_no=batch_no,
            username=username,
            source=source,
            created_at=datetime.now().strftime("%H:%M:%S"),
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def add_batch(self, reqs, username: str, source: str = "ui") -> list:
        """
        Add multiple print requests atomically (under a single lock) so that a
        multi-line submission is queued together and paired together in 2-up mode.
        Returns the list of created jobs in the same order as `reqs`.
        """
        self._fix_roll(reqs)
        jobs = []
        with self._lock:
            for req in reqs:
                # Only product labels carry a lot number. Ingredients and FSSAI
                # logo stickers would each burn one of the day's sequence.
                batch_no = get_next_batch_number() if req.label_type == "product" else ""
                job = QueueJob(
                    id=uuid.uuid4().hex[:8],
                    req=req,
                    batch_no=batch_no,
                    username=username,
                    source=source,
                    created_at=datetime.now().strftime("%H:%M:%S"),
                )
                self._jobs[job.id] = job
                jobs.append(job)
        return jobs

    def add_test(self, req: PrintRequest, username: str) -> QueueJob:
        """
        Queue a calibration label. It prints "TEST" where the batch number
        goes, so it neither uses up one of the day's lot numbers nor ends up
        in the print history.
        """
        self._fix_roll([req])
        job = QueueJob(
            id=uuid.uuid4().hex[:8],
            req=req,
            batch_no="TEST",
            username=username,
            source="ui",
            created_at=datetime.now().strftime("%H:%M:%S"),
            test=True,
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def list_jobs(self) -> list:
        """Return all non-terminal jobs (queued + printing)."""
        with self._lock:
            return [
                j.to_dict()
                for j in self._jobs.values()
                if j.status in ("queued", "printing")
            ]

    def list_all(self) -> list:
        """Return all jobs including completed/failed/cancelled."""
        with self._lock:
            return [j.to_dict() for j in self._jobs.values()]

    def cancel(self, job_id: str) -> bool:
        """Cancel a queued job. Returns True if cancelled, False if not found or already processing."""
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status != "queued":
                return False  # can't cancel if already printing/done
            job.finish("cancelled")
            return True

    def cancel_all(self) -> int:
        """Cancel all queued jobs. Returns count of cancelled jobs."""
        count = 0
        with self._lock:
            for job in self._jobs.values():
                if job.status == "queued":
                    job.finish("cancelled")
                    count += 1
        return count

    def _failed(self, job_id: Optional[str]) -> list:
        """Failed jobs: the one with job_id, or all of them when job_id is None. Call under the lock."""
        return [j for j in self._jobs.values()
                if j.status == "failed" and (job_id is None or j.id == job_id)]

    def retry(self, job_id: Optional[str] = None) -> int:
        """
        Put failed jobs back in the queue: one by id, or every failed job.
        They keep their batch number, since nothing was printed under it.
        Returns how many were requeued.
        """
        with self._lock:
            jobs = self._failed(job_id)
            for job in jobs:
                job.status = "queued"
                job.error = None
                job.finished_at, job.finished_ts = "", 0.0
                # To the back, as if just submitted: the retry prints after
                # anything that was already waiting.
                self._jobs.move_to_end(job.id)
            return len(jobs)

    def dismiss(self, job_id: Optional[str] = None) -> int:
        """Clear failed jobs from the list without printing them. Returns how many."""
        with self._lock:
            jobs = self._failed(job_id)
            for job in jobs:
                job.status = "dismissed"
            return len(jobs)

    def _process_loop(self):
        """
        Background worker. Jobs print in FIFO order, each in its own label type.

        A 'single' or 'large' job prints on its own (one label per row, using
        the printer's native copy count). A 'double' job prints together with
        every 'double' job queued straight after it: their labels are
        flattened into one sequence and printed two side by side per row; an
        odd final label prints alone (right column blank).

        The body is wrapped because this runs on a daemon thread with nothing
        above it to catch anything. Rendering reads settings.json and raises
        PermissionError when the sibling process holds the file open;
        _log_job writes to users.db and raises OperationalError when that lock
        is contended. Either one, unhandled, killed the worker for good: jobs
        kept queueing, the UI spinner turned forever, and nothing printed again
        until someone restarted run.bat — with no message anywhere saying why.
        """
        while True:
            try:
                job = self._next_queued()
                if job is None:
                    did_work = False
                elif job.req.roll_type == "double":
                    did_work = self._process_double_batch()
                else:
                    did_work = self._process_single(job)
                if not did_work:
                    time.sleep(0.3)
            except Exception:
                _log.exception("Print worker hit an error; continuing.")
                time.sleep(1)

    def _log_job(self, job):
        """Log a completed product job (ingredients, FSSAI logo and test labels are not logged)."""
        if job.req.label_type == "product" and not job.test:
            log_print(
                username=job.username,
                source=job.source,
                product=job.req.product,
                weight=job.req.weight,
                quantity=job.req.quantity,
                batch_no=job.batch_no,
                packed_on=job.req.packed_on,
                best_before=job.req.best_before,
                as_typed=job.req.as_typed,
                roll_type=job.req.roll_type,
            )

    def _process_single(self, job) -> bool:
        """Print one job on a one-label-per-row roll (single or large)."""
        with self._lock:
            # Cancelled since the loop picked it: go round again
            if job.status != "queued":
                return True
            job.status = "printing"

        try:
            success = print_label(job.req, job.batch_no)
        except Exception as e:
            success = False
            job.error = str(e)

        with self._lock:
            if success:
                job.finish("done")
            else:
                job.finish("failed")
                if not job.error:
                    job.error = "Printer error"

        # Logged outside the lock: this is a SQLite write against a users.db
        # that two processes contend for, so it can block for the full timeout.
        # A failure to log must not discard a print that actually happened.
        if success:
            try:
                self._log_job(job)
            except Exception:
                _log.exception("Could not write print log for job %s", job.id)

        self._cleanup()
        return True

    def _process_double_batch(self) -> bool:
        """Print the run of 2-up jobs at the head of the queue, side by side."""
        # Grab queued jobs (FIFO) up to the first one of another label type,
        # and mark them printing.
        with self._lock:
            jobs = []
            for j in self._jobs.values():
                if j.status != "queued":
                    continue
                if j.req.roll_type != "double":
                    break
                jobs.append(j)
            for j in jobs:
                j.status = "printing"

        if not jobs:
            return False

        # Render each job's label once, then expand into individual sticker units.
        units = []            # one image per physical sticker
        failed_ids = set()
        for job in jobs:
            try:
                img = render_label(job.req, job.batch_no)
            except Exception as e:
                job.error = str(e)
                failed_ids.add(job.id)
                continue
            units.extend([img] * job.req.quantity)

        # Pair units two-per-row; odd leftover prints alone (right column blank).
        rows = []
        for i in range(0, len(units), 2):
            left = units[i]
            right = units[i + 1] if i + 1 < len(units) else None
            rows.append((left, right))

        success = print_double_rows(rows)

        printed = []
        with self._lock:
            for job in jobs:
                if job.id in failed_ids:
                    job.finish("failed")
                    if not job.error:
                        job.error = "Render error"
                elif success:
                    job.finish("done")
                    printed.append(job)
                else:
                    job.finish("failed")
                    if not job.error:
                        job.error = "Printer error"

        # Logged outside the lock, as in _process_single_next: the SQLite
        # write can block for its full timeout, and holding the lock that
        # long froze every queue request. A failed log must not undo a print.
        for job in printed:
            try:
                self._log_job(job)
            except Exception:
                _log.exception("Could not write print log for job %s", job.id)

        self._cleanup()
        return True

    def _next_queued(self) -> Optional[QueueJob]:
        """Get the next queued job (FIFO)."""
        with self._lock:
            for job in self._jobs.values():
                if job.status == "queued":
                    return job
        return None

    def _cleanup(self):
        """Remove old terminal jobs, keeping the most recent 50."""
        with self._lock:
            terminal = [
                jid
                for jid, j in self._jobs.items()
                if j.status in ("done", "failed", "cancelled", "dismissed")
            ]
            # Keep only the last 50 terminal jobs
            to_remove = terminal[:-50] if len(terminal) > 50 else []
            for jid in to_remove:
                del self._jobs[jid]


# ── Singleton ─────────────────────────────────
_queue = PrintQueue()


def get_queue() -> PrintQueue:
    return _queue
