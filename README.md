# WhatsApp Server 🚀

A dedicated WhatsApp microservice that wraps [Evolution API](https://doc.evolution-api.com/) and applies **human-behavior simulation** so WhatsApp's anti-automation systems cannot detect that messages are being sent programmatically.

---

## Architecture

```
Main Backend (app.py)
      │
      │  HTTP POST  X-WA-Secret: <secret>
      ▼
WhatsApp Microservice  ← THIS SERVICE
      │
      │  Typing presence · Random delays · Sequential queue
      ▼
Evolution API (https://evolution-api-10a6.onrender.com)
      │
      ▼
WhatsApp
```

---

## Anti-Detection Techniques

| Technique | Detail |
|---|---|
| **Typing indicator** | Shows "typing…" (`composing` presence) before every text message |
| **Recording indicator** | Shows "recording…" presence before every media message |
| **Message-length-aware delay** | Typing time scales with message character count |
| **Randomized inter-message wait** | 8–25 seconds (random) between consecutive messages |
| **Sub-second jitter** | Extra 0–500 ms random noise on every timing value |
| **Sequential queue** | Only ONE message is processed at a time — never parallel |
| **Retry with exponential back-off** | Failed sends retry up to 3× with jitter |

---

## Folder Structure

```
whatsapp_server/
├── server.py           # Flask app — REST endpoints
├── wsgi.py             # Gunicorn entry point
├── whatsapp_client.py  # Evolution API low-level calls
├── message_queue.py    # Thread-safe sequential queue
├── anti_detect.py      # Presence + timing utilities
├── config.py           # Env var loading & validation
├── requirements.txt    # Python dependencies
├── .env.example        # Environment variable template
├── render.yaml         # Render.com deployment config
└── README.md           # This file
```

---

## Setup

### 1. Clone / copy this folder

This folder is self-contained. Copy it to its own repository or deploy directly from within the monorepo.

### 2. Create `.env` from the example

```bash
cp .env.example .env
```

Fill in:
| Variable | Where to find it |
|---|---|
| `EVOLUTION_API_URL` | Your Evolution API Render URL |
| `EVOLUTION_API_KEY` | Evolution API dashboard → API key |
| `EVOLUTION_INSTANCE` | The instance name you created |
| `WA_SERVER_SECRET` | Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run locally

```bash
python server.py
```

Or with Gunicorn:
```bash
gunicorn wsgi:application --workers 1 --threads 4 --timeout 120
```

> ⚠️ **Always use `--workers 1`** — multiple workers would bypass the sequential queue and send messages in parallel.

---

## Deploy on Render

1. Push `whatsapp_server/` to a GitHub repo (or as a subdirectory).
2. Create a new **Web Service** on Render, pointing to this folder.
3. Render will detect `render.yaml` and configure everything automatically.
4. Set the sensitive env vars manually in the Render dashboard:
   - `EVOLUTION_API_URL`
   - `EVOLUTION_API_KEY`
   - `EVOLUTION_INSTANCE`
5. Copy the auto-generated `WA_SERVER_SECRET` from Render dashboard → paste it into your main backend's `.env` as `WA_SERVER_SECRET`.

---

## API Reference

All endpoints (except `/health`) require:
```
X-WA-Secret: <your WA_SERVER_SECRET>
```

### `GET /health`
Public liveness check.
```json
{ "status": "ok", "service": "whatsapp-server" }
```

### `GET /status`
Evolution API connection status.

### `GET /queue-stats`
Current message queue statistics.

### `GET /job/<job_id>`
Poll the status of a specific message job.
```json
{ "success": true, "job": { "status": "sent", ... } }
```

### `POST /send/text`
Send a text message.
```json
{
  "number":  "9876543210",
  "message": "Hello! This is your digital pass."
}
```

### `POST /send/image`
Send an image from a public URL.
```json
{
  "number":    "9876543210",
  "image_url": "https://res.cloudinary.com/...",
  "caption":   "Your digital pass is attached."
}
```

### `POST /send/image-base64`
Send an image from base64 data.
```json
{
  "number":      "9876543210",
  "base64_data": "<base64 string>",
  "caption":     "Your pass",
  "mime_type":   "image/jpeg"
}
```

### `POST /send/document`
Send a document/file from a public URL.
```json
{
  "number":       "9876543210",
  "document_url": "https://example.com/report.pdf",
  "filename":     "report.pdf",
  "caption":      "Here is your report"
}
```

**All send endpoints return immediately with `HTTP 202 Accepted`:**
```json
{
  "success": true,
  "job_id":  "550e8400-e29b-41d4-a716-446655440000",
  "status":  "pending"
}
```
Poll `/job/<job_id>` to check delivery status.

---

## Integration with Main Backend

In your main `app.py`, use the `WhatsAppService` helper:

```python
from whatsapp_service import WhatsAppService

wa = WhatsAppService()  # reads WA_SERVER_URL + WA_SERVER_SECRET from .env

# Send a text
job = wa.send_text("9876543210", "Hello from the main server!")

# Send an image by URL
job = wa.send_image("9876543210", "https://cloudinary.com/...", "Caption here")
```

---

## Important Notes

- **Never run with more than 1 Gunicorn worker** — the queue lives in memory.
- The inter-message delay (8–25 seconds) means 100 messages will take ~20–40 minutes. Plan accordingly.
- Always **warm up a new WhatsApp number** by using it manually for 2–5 days before enabling automation.
- Do not send more than **50–100 messages/day** on a fresh number.
