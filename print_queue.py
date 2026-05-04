"""
Thread-safe print queue with cancel support.

Jobs are added to a queue and processed one at a time by a background worker.
Each job gets a unique ID so it can be listed or cancelled before it prints.
"""

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from parser import PrintRequest
from printer import print_label
from batch_manager import get_next_batch_number
from logger import log_print


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
        batch_no = get_next_batch_number() if req.label_type != "ingredients" else ""
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
        """Background worker that processes jobs one at a time."""
        while True:
            job = self._next_queued()
            if job is None:
                time.sleep(0.3)
                continue

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
                    # Log successful prints
                    if job.req.label_type != "ingredients":
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
                else:
                    job.status = "failed"
                    if not job.error:
                        job.error = "Printer error"

            # Clean up old terminal jobs (keep last 50)
            self._cleanup()

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
