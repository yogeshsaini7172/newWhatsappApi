"""
server.py — WhatsApp Microservice Flask application.

This is the main entry point for the dedicated WhatsApp server.
The main backend (app.py) calls this service's endpoints to send messages.

ENDPOINTS:
  GET  /health           — liveness check (no auth required)
  GET  /status           — Evolution API instance status (auth required)
  GET  /queue-stats      — message queue statistics (auth required)
  GET  /job/<job_id>     — poll a specific job's status (auth required)

  POST /send/text        — enqueue a WhatsApp text message
  POST /send/image       — enqueue a WhatsApp image (by URL)
  POST /send/image-base64 — enqueue a WhatsApp image (base64 data)
  POST /send/document    — enqueue a WhatsApp document (by URL)

AUTHENTICATION:
  All /send/* and /status endpoints require the header:
    X-WA-Secret: <WA_SERVER_SECRET from .env>
"""

import logging
import sys
from functools import wraps

from flask import Flask, request, jsonify

import config
import message_queue as mq
import whatsapp_client as wa

# ─── Logging setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ─── App setup ────────────────────────────────────────────────────────────────
app = Flask(__name__)


# ─── Auth decorator ───────────────────────────────────────────────────────────

def require_secret(f):
    """
    Decorator that validates the X-WA-Secret header on every protected endpoint.
    Returns HTTP 401 if the header is missing or incorrect.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        provided = request.headers.get("X-WA-Secret", "")
        if not provided or provided != config.WA_SERVER_SECRET:
            logger.warning("Unauthorized request to %s from %s", request.path, request.remote_addr)
            return jsonify({"error": "Unauthorized. Provide a valid X-WA-Secret header."}), 401
        return f(*args, **kwargs)
    return decorated


# ─── Helper ───────────────────────────────────────────────────────────────────

def _ok(data: dict, status: int = 200):
    return jsonify({"success": True, **data}), status


def _err(message: str, status: int = 400):
    return jsonify({"success": False, "error": message}), status


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Public liveness check — used by Render/load-balancer health checks."""
    return jsonify({"status": "ok", "service": "whatsapp-server"}), 200


@app.get("/status")
@require_secret
def status():
    """Return the current Evolution API instance connection status."""
    instance_info = wa.get_instance_status()
    return _ok({"instance": instance_info})


@app.get("/queue-stats")
@require_secret
def queue_stats():
    """Return statistics about the message queue."""
    return _ok({"queue": mq.get_queue_stats()})


@app.get("/job/<job_id>")
@require_secret
def job_status(job_id: str):
    """Poll the status of a specific queued message job."""
    status = mq.get_job_status(job_id)
    if status is None:
        return _err(f"Job '{job_id}' not found", 404)
    return _ok({"job": status})


# ── Send Text ──────────────────────────────────────────────────────────────────

@app.post("/send/text")
@require_secret
def send_text():
    """
    Enqueue a WhatsApp text message.

    Request JSON body:
      {
        "number":  "9876543210",          # required — 10-digit or full international
        "message": "Hello from the bot!"  # required — text to send
      }

    Response:
      {
        "success": true,
        "job_id":  "<uuid>",
        "status":  "pending"
      }
    """
    body = request.get_json(silent=True) or {}
    number = body.get("number", "").strip()
    message = body.get("message", "").strip()

    if not number:
        return _err("'number' is required")
    if not message:
        return _err("'message' is required")

    job_id = mq.enqueue_text(number, message)
    return _ok({"job_id": job_id, "status": "pending"}, 202)


# ── Send Image (URL) ───────────────────────────────────────────────────────────

@app.post("/send/image")
@require_secret
def send_image():
    """
    Enqueue a WhatsApp image message from a public URL.

    Request JSON body:
      {
        "number":    "9876543210",         # required
        "image_url": "https://...",        # required — publicly accessible URL
        "caption":   "Check this out!"    # optional
      }
    """
    body = request.get_json(silent=True) or {}
    number = body.get("number", "").strip()
    image_url = body.get("image_url", "").strip()
    caption = body.get("caption", "").strip()

    if not number:
        return _err("'number' is required")
    if not image_url:
        return _err("'image_url' is required")

    job_id = mq.enqueue_image_url(number, image_url, caption)
    return _ok({"job_id": job_id, "status": "pending"}, 202)


# ── Send Image (base64) ────────────────────────────────────────────────────────

@app.post("/send/image-base64")
@require_secret
def send_image_base64():
    """
    Enqueue a WhatsApp image message from raw base64 data.

    Request JSON body:
      {
        "number":      "9876543210",       # required
        "base64_data": "<base64 string>",  # required (with or without data: header)
        "caption":     "Look!",            # optional
        "mime_type":   "image/jpeg"        # optional, default: image/jpeg
      }
    """
    body = request.get_json(silent=True) or {}
    number = body.get("number", "").strip()
    base64_data = body.get("base64_data", "").strip()
    caption = body.get("caption", "").strip()
    mime_type = body.get("mime_type", "image/jpeg").strip()

    if not number:
        return _err("'number' is required")
    if not base64_data:
        return _err("'base64_data' is required")

    job_id = mq.enqueue_image_base64(number, base64_data, caption, mime_type)
    return _ok({"job_id": job_id, "status": "pending"}, 202)


# ── Send Document ──────────────────────────────────────────────────────────────

@app.post("/send/document")
@require_secret
def send_document():
    """
    Enqueue a WhatsApp document message from a public URL.

    Request JSON body:
      {
        "number":       "9876543210",      # required
        "document_url": "https://...",     # required — publicly accessible URL
        "filename":     "report.pdf",      # required — name shown to recipient
        "caption":      "Here's the doc"  # optional
      }
    """
    body = request.get_json(silent=True) or {}
    number = body.get("number", "").strip()
    document_url = body.get("document_url", "").strip()
    filename = body.get("filename", "document").strip()
    caption = body.get("caption", "").strip()

    if not number:
        return _err("'number' is required")
    if not document_url:
        return _err("'document_url' is required")

    job_id = mq.enqueue_document(number, document_url, filename, caption)
    return _ok({"job_id": job_id, "status": "pending"}, 202)


# ─── Startup ──────────────────────────────────────────────────────────────────

def create_app():
    """Factory function called at startup."""
    try:
        config.validate_config()
        logger.info("✅ Config validated — Evolution API: %s | Instance: %s",
                    config.EVOLUTION_API_URL, config.EVOLUTION_INSTANCE)
    except ValueError as exc:
        logger.critical("❌ Config error: %s", exc)
        sys.exit(1)

    mq.start_worker()
    logger.info("✅ Message queue worker started")
    return app


# ─── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    application = create_app()
    logger.info("🚀 WhatsApp server starting on port %d", config.PORT)
    application.run(host="0.0.0.0", port=config.PORT, debug=False)
