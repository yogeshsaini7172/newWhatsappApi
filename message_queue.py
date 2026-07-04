"""
message_queue.py — Thread-safe sequential message queue.

WHY A QUEUE?
  WhatsApp's spam detection watches for simultaneous or rapid-fire sends.
  This queue ensures messages are always processed ONE AT A TIME, with a
  mandatory inter-message delay between each job.

HOW IT WORKS:
  - Callers push a job dict onto the queue (non-blocking, returns immediately).
  - A single background worker thread dequeues and processes jobs sequentially.
  - Between each job the worker sleeps for a randomised inter-message delay.
  - Each job's status (pending → processing → sent/failed) is tracked in memory.

THREAD SAFETY:
  - queue.Queue is thread-safe; all status mutations are protected by a Lock.
"""

import queue
import threading
import time
import uuid
import logging
from typing import Optional

import config
import anti_detect as ad
import whatsapp_client as wa

logger = logging.getLogger(__name__)

# ─── Internal state ───────────────────────────────────────────────────────────

_job_queue: queue.Queue = queue.Queue()
_job_status: dict[str, dict] = {}          # job_id → status dict
_status_lock: threading.Lock = threading.Lock()
_worker_thread: Optional[threading.Thread] = None
_running: bool = False

# ─── Job status constants ─────────────────────────────────────────────────────
PENDING    = "pending"
PROCESSING = "processing"
SENT       = "sent"
FAILED     = "failed"


# ─── Worker ───────────────────────────────────────────────────────────────────

def _update_status(job_id: str, **kwargs) -> None:
    with _status_lock:
        if job_id in _job_status:
            _job_status[job_id].update(kwargs)


def _process_job(job: dict) -> None:
    """Execute one message job and update its status."""
    job_id = job["id"]
    job_type = job["type"]   # "text" | "image_url" | "image_base64" | "document"
    number = job["number"]

    _update_status(job_id, status=PROCESSING, started_at=time.time())
    logger.info("[Queue] Processing job %s (%s → %s)", job_id, job_type, number)

    try:
        if job_type == "text":
            result = wa.send_text_message(number, job["text"])

        elif job_type == "image_url":
            result = wa.send_image_message(
                number,
                job["image_url"],
                job.get("caption", ""),
            )

        elif job_type == "image_base64":
            result = wa.send_image_base64(
                number,
                job["base64_data"],
                job.get("caption", ""),
                job.get("mime_type", "image/jpeg"),
            )

        elif job_type == "document":
            result = wa.send_document_message(
                number,
                job["document_url"],
                job.get("filename", "document"),
                job.get("caption", ""),
            )

        else:
            raise ValueError(f"Unknown job type: {job_type}")

        _update_status(job_id, status=SENT, result=result, finished_at=time.time())
        logger.info("[Queue] Job %s → SENT", job_id)

    except Exception as exc:
        logger.error("[Queue] Job %s → FAILED: %s", job_id, exc)
        _update_status(job_id, status=FAILED, error=str(exc), finished_at=time.time())


def _worker_loop() -> None:
    """
    Main worker loop — runs in a daemon thread.
    Picks one job at a time, processes it, then waits for the inter-message
    delay before picking the next job.
    """
    global _running
    logger.info("[Queue] Worker thread started")
    while _running:
        try:
            job = _job_queue.get(timeout=1)   # blocks for 1 s then loops
        except queue.Empty:
            continue

        _process_job(job)
        _job_queue.task_done()

        # Inter-message delay AFTER processing (not before)
        # Only sleep if there are more jobs waiting — saves time on the last job
        if not _job_queue.empty():
            delay = ad.random_delay()
            logger.info("[Queue] Inter-message delay: %.1fs", delay)

    logger.info("[Queue] Worker thread stopped")


# ─── Public API ───────────────────────────────────────────────────────────────

def start_worker() -> None:
    """Start the background worker thread. Call once at app startup."""
    global _worker_thread, _running
    if _worker_thread and _worker_thread.is_alive():
        return
    _running = True
    _worker_thread = threading.Thread(target=_worker_loop, daemon=True, name="wa-queue-worker")
    _worker_thread.start()
    logger.info("[Queue] Worker started (PID thread: %s)", _worker_thread.ident)


def stop_worker() -> None:
    """Gracefully stop the worker (waits for current job to finish)."""
    global _running
    _running = False
    if _worker_thread:
        _worker_thread.join(timeout=60)
    logger.info("[Queue] Worker stopped")


def enqueue_text(number: str, text: str) -> str:
    """
    Add a text message to the queue.
    Returns the job_id immediately (non-blocking).
    """
    job_id = str(uuid.uuid4())
    job = {"id": job_id, "type": "text", "number": number, "text": text}
    with _status_lock:
        _job_status[job_id] = {"status": PENDING, "type": "text", "number": number, "queued_at": time.time()}
    _job_queue.put(job)
    logger.info("[Queue] Enqueued text job %s for %s", job_id, number)
    return job_id


def enqueue_image_url(number: str, image_url: str, caption: str = "") -> str:
    """
    Add an image (by public URL) message to the queue.
    Returns the job_id immediately.
    """
    job_id = str(uuid.uuid4())
    job = {"id": job_id, "type": "image_url", "number": number, "image_url": image_url, "caption": caption}
    with _status_lock:
        _job_status[job_id] = {"status": PENDING, "type": "image_url", "number": number, "queued_at": time.time()}
    _job_queue.put(job)
    logger.info("[Queue] Enqueued image_url job %s for %s", job_id, number)
    return job_id


def enqueue_image_base64(number: str, base64_data: str, caption: str = "", mime_type: str = "image/jpeg") -> str:
    """
    Add an image (base64 data) message to the queue.
    Returns the job_id immediately.
    """
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id, "type": "image_base64", "number": number,
        "base64_data": base64_data, "caption": caption, "mime_type": mime_type,
    }
    with _status_lock:
        _job_status[job_id] = {"status": PENDING, "type": "image_base64", "number": number, "queued_at": time.time()}
    _job_queue.put(job)
    logger.info("[Queue] Enqueued image_base64 job %s for %s", job_id, number)
    return job_id


def enqueue_document(number: str, document_url: str, filename: str, caption: str = "") -> str:
    """
    Add a document message to the queue.
    Returns the job_id immediately.
    """
    job_id = str(uuid.uuid4())
    job = {
        "id": job_id, "type": "document", "number": number,
        "document_url": document_url, "filename": filename, "caption": caption,
    }
    with _status_lock:
        _job_status[job_id] = {"status": PENDING, "type": "document", "number": number, "queued_at": time.time()}
    _job_queue.put(job)
    logger.info("[Queue] Enqueued document job %s for %s", job_id, number)
    return job_id


def get_job_status(job_id: str) -> Optional[dict]:
    """Return the status dict for a given job_id, or None if not found."""
    with _status_lock:
        return dict(_job_status.get(job_id, {})) or None


def get_queue_stats() -> dict:
    """Return current queue statistics."""
    with _status_lock:
        all_jobs = list(_job_status.values())
    return {
        "queue_size": _job_queue.qsize(),
        "total_jobs":  len(all_jobs),
        "pending":     sum(1 for j in all_jobs if j["status"] == PENDING),
        "processing":  sum(1 for j in all_jobs if j["status"] == PROCESSING),
        "sent":        sum(1 for j in all_jobs if j["status"] == SENT),
        "failed":      sum(1 for j in all_jobs if j["status"] == FAILED),
    }
