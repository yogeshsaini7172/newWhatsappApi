"""
whatsapp_client.py — Low-level Evolution API wrapper.

This module handles all direct HTTP communication with the Evolution API.
All public functions apply anti-detection measures (presence simulation +
randomized delays) before sending messages.

Retry logic is built in: if a request fails with a transient error
(network timeout, 5xx response), it retries up to MAX_RETRIES times
with exponential back-off + jitter.
"""

import time
import random
import logging
import requests

import config
import anti_detect as ad

logger = logging.getLogger(__name__)


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _headers() -> dict:
    return {
        "apikey": config.EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }


def _post_with_retry(url: str, payload: dict) -> dict:
    """
    POST to Evolution API with exponential back-off retry.

    Retries on:
      - requests.exceptions (timeout, connection error, etc.)
      - HTTP 5xx responses

    Raises RuntimeError after MAX_RETRIES exhausted.
    Returns the parsed JSON response dict on success.
    """
    last_error = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            resp = requests.post(url, json=payload, headers=_headers(), timeout=30)
            if resp.status_code in (200, 201):
                return resp.json()
            elif resp.status_code >= 500:
                last_error = f"Server error {resp.status_code}: {resp.text[:300]}"
                logger.warning("Attempt %d/%d — %s", attempt, config.MAX_RETRIES, last_error)
            elif resp.status_code == 400:
                # Bad request — don't retry, just raise immediately
                raise RuntimeError(f"Evolution API bad request (400): {resp.text[:300]}")
            elif resp.status_code == 401:
                raise RuntimeError("Evolution API authentication failed (401). Check EVOLUTION_API_KEY.")
            else:
                last_error = f"Unexpected status {resp.status_code}: {resp.text[:300]}"
                logger.warning("Attempt %d/%d — %s", attempt, config.MAX_RETRIES, last_error)
        except requests.exceptions.Timeout:
            last_error = "Request timed out"
            logger.warning("Attempt %d/%d — timeout reaching Evolution API", attempt, config.MAX_RETRIES)
        except requests.exceptions.ConnectionError as exc:
            last_error = str(exc)
            logger.warning("Attempt %d/%d — connection error: %s", attempt, config.MAX_RETRIES, exc)
        except RuntimeError:
            raise  # Pass through non-retryable errors

        if attempt < config.MAX_RETRIES:
            # Exponential back-off with jitter
            backoff = (config.RETRY_BASE_DELAY * (2 ** (attempt - 1))) + random.uniform(0, 2)
            logger.info("Retrying in %.1fs…", backoff)
            time.sleep(backoff)

    raise RuntimeError(
        f"Evolution API call failed after {config.MAX_RETRIES} attempts. Last error: {last_error}"
    )


# ─── Public API ───────────────────────────────────────────────────────────────

def get_instance_status() -> dict:
    """
    Fetch the current connection status of the Evolution API instance.
    Returns the raw JSON dict from the API.
    Does NOT apply any anti-detection delays (this is a health-check call).
    """
    url = f"{config.EVOLUTION_API_URL}/instance/fetchInstances"
    try:
        resp = requests.get(url, headers=_headers(), timeout=15)
        data = resp.json()
        # Find our specific instance in the list
        if isinstance(data, list):
            for inst in data:
                name = inst.get("instance", {}).get("instanceName") or inst.get("instanceName")
                if name == config.EVOLUTION_INSTANCE:
                    return inst
            return {"error": f"Instance '{config.EVOLUTION_INSTANCE}' not found", "all": data}
        return data
    except Exception as exc:
        return {"error": str(exc)}


def send_text_message(number: str, text: str) -> dict:
    """
    Send a WhatsApp text message to `number` with full anti-detection:
      1. Format the phone number
      2. Simulate composing presence (typing indicator)
      3. POST /message/sendText
      4. Return the API response dict

    The INTER-MESSAGE delay (8–25s) is handled by the message queue,
    NOT here, so back-to-back calls within one job are still spaced out.
    """
    formatted = ad.format_phone_number(number)
    logger.info("Sending text to %s (%d chars)", formatted, len(text))

    # Show typing indicator for realistic duration
    ad.simulate_human_text_sending(formatted, text)

    url = f"{config.EVOLUTION_API_URL}/message/sendText/{config.EVOLUTION_INSTANCE}"
    payload = {
        "number": formatted,
        "text": text,
        "options": {
            "delay": random.randint(800, 2500),   # ms delay inside Evolution API itself
            "presence": "composing",               # keep presence while API processes
        },
    }
    result = _post_with_retry(url, payload)
    logger.info("Text message sent to %s — message ID: %s", formatted, result.get("key", {}).get("id", "?"))
    return result


def send_image_message(number: str, image_url: str, caption: str = "") -> dict:
    """
    Send a WhatsApp image message using a public URL.
      1. Format the phone number
      2. Simulate recording/uploading presence
      3. POST /message/sendMedia

    `image_url` must be a publicly accessible URL (Cloudinary, S3, etc.)
    `caption` is optional text shown below the image.
    """
    formatted = ad.format_phone_number(number)
    logger.info("Sending image to %s — url: %s", formatted, image_url[:60])

    # Show 'recording' presence (natural for media)
    ad.simulate_human_media_sending(formatted)

    url = f"{config.EVOLUTION_API_URL}/message/sendMedia/{config.EVOLUTION_INSTANCE}"
    payload = {
        "number": formatted,
        "mediatype": "image",
        "media": image_url,
        "caption": caption,
        "options": {
            "delay": random.randint(1200, 3500),
            "presence": "composing",
        },
    }
    result = _post_with_retry(url, payload)
    logger.info("Image sent to %s — message ID: %s", formatted, result.get("key", {}).get("id", "?"))
    return result


def send_image_base64(number: str, base64_data: str, caption: str = "", mime_type: str = "image/jpeg") -> dict:
    """
    Send a WhatsApp image from raw base64 data.
    Useful when the caller cannot provide a public URL.

    `base64_data` — raw base64 string (with or without the data: header)
    `mime_type`   — e.g. "image/jpeg", "image/png"
    """
    formatted = ad.format_phone_number(number)
    logger.info("Sending base64 image (%s) to %s", mime_type, formatted)

    # Strip data-URI prefix if present
    if "," in base64_data:
        base64_data = base64_data.split(",", 1)[1]

    ad.simulate_human_media_sending(formatted)

    url = f"{config.EVOLUTION_API_URL}/message/sendMedia/{config.EVOLUTION_INSTANCE}"
    payload = {
        "number": formatted,
        "mediatype": "image",
        "media": f"data:{mime_type};base64,{base64_data}",
        "caption": caption,
        "options": {
            "delay": random.randint(1200, 3500),
            "presence": "composing",
        },
    }
    result = _post_with_retry(url, payload)
    logger.info("Base64 image sent to %s", formatted)
    return result


def send_document_message(number: str, document_url: str, filename: str, caption: str = "") -> dict:
    """
    Send a file/document via WhatsApp.
    `document_url` must be a publicly accessible URL.
    """
    formatted = ad.format_phone_number(number)
    logger.info("Sending document '%s' to %s", filename, formatted)

    ad.simulate_human_media_sending(formatted)

    url = f"{config.EVOLUTION_API_URL}/message/sendMedia/{config.EVOLUTION_INSTANCE}"
    payload = {
        "number": formatted,
        "mediatype": "document",
        "media": document_url,
        "fileName": filename,
        "caption": caption,
        "options": {
            "delay": random.randint(1200, 3500),
            "presence": "composing",
        },
    }
    result = _post_with_retry(url, payload)
    logger.info("Document sent to %s", formatted)
    return result
