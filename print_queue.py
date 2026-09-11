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
    status: str = "queued"  # queued | printing | done | failed | cancelled
    created_at: str = ""
    error: Optional[str] = None

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
            "batch_no": self.batch_no,
            "username": self.username,
            "source": self.source,
            "status": self.status,
            "created_at": self.created_at,
            "error": self.error,
        }


class PrintQueue:
    def __init__(self):
        self._lock = threading.Lock()
        # OrderedDict preserves insertion order — oldest first
        self._jobs: OrderedDict[str, QueueJob] = OrderedDict()
        self._worker = threading.Thread(target=self._process_loop, daemon=True)
        self._worker.start()

    def add(self, req: PrintRequest, username: str, source: str = "ui") -> QueueJob:
        """Add a print request to the queue. Returns the created job."""
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
            job.status = "cancelled"
            return True

    def cancel_all(self) -> int:
        """Cancel all queued jobs. Returns count of cancelled jobs."""
        count = 0
        with self._lock:
            for job in self._jobs.values():
                if job.status == "queued":
                    job.status = "cancelled"
                    count += 1
        return count

    def _process_loop(self):
        """
        Background worker.

        In 'single' mode each job is printed on its own (one label per row,
        using the printer's native copy count). In 'double' mode all currently
        queued labels are flattened into a single FIFO sequence and printed two
        side by side per row; an odd final label prints alone (right column blank).

        The body is wrapped because this runs on a daemon thread with nothing
        above it to catch anything. get_roll_type() reads settings.json and
        raises PermissionError when the sibling process holds the file open;
        _log_job writes to users.db and raises OperationalError when that lock
        is contended. Either one, unhandled, killed the worker for good: jobs
        kept queueing, the UI spinner turned forever, and nothing printed again
        until someone restarted run.bat — with no message anywhere saying why.
        """
        while True:
            try:
                if get_roll_type() == "double":
                    did_work = self._process_double_batch()
                else:
                    did_work = self._process_single_next()
                if not did_work:
                    time.sleep(0.3)
            except Exception:
                _log.exception("Print worker hit an error; continuing.")
                time.sleep(1)

    def _log_job(self, job):
        """Log a completed product job (ingredients and FSSAI logo labels are not logged)."""
        if job.req.label_type == "product":
            log_print(
                username=job.username,
                source=job.source,
                product=job.req.product,
                weight=job.req.weight,
                quantity=job.req.quantity,
                batch_no=job.batch_no,
                packed_on=job.req.packed_on,
                best_before=job.req.best_before,
            )

    def _process_single_next(self) -> bool:
        """Print the next queued job on a single-label-per-row roll."""
        job = self._next_queued()
        if job is None:
            return False

        with self._lock:
            job.status = "printing"

        try:
            success = print_label(job.req, job.batch_no)
        except Exception as e:
            success = False
            job.error = str(e)

        with self._lock:
            if success:
                job.status = "done"
            else:
                job.status = "failed"
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
        """Print all currently-queued labels 2-up (side by side)."""
        # Grab all queued jobs (FIFO) and mark them printing.
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.status == "queued"]
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

        with self._lock:
            for job in jobs:
                if job.id in failed_ids:
                    job.status = "failed"
                    if not job.error:
                        job.error = "Render error"
                elif success:
                    job.status = "done"
                    self._log_job(job)
                else:
                    job.status = "failed"
                    if not job.error:
                        job.error = "Printer error"

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
                if j.status in ("done", "failed", "cancelled")
            ]
            # Keep only the last 50 terminal jobs
            to_remove = terminal[:-50] if len(terminal) > 50 else []
            for jid in to_remove:
                del self._jobs[jid]


# ── Singleton ─────────────────────────────────
_queue = PrintQueue()


def get_queue() -> PrintQueue:
    return _queue
