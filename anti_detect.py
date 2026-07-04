"""
anti_detect.py — Human-behavior simulation utilities.

Every message sent through this server goes through these helpers to make
WhatsApp's systems believe the messages are being typed and sent by a human.

Techniques used:
  1. Randomized inter-message delay (8–25 seconds by default)
  2. "Composing" / "recording" presence shown before each message
  3. Message-length-aware typing duration
  4. Small random jitter added to every timing value
"""

import time
import random
import logging
import requests

import config

logger = logging.getLogger(__name__)


# ─── Phone Number Formatting ─────────────────────────────────────────────────

def format_phone_number(number: str) -> str:
    """
    Normalise a phone number to the format Evolution API expects:
      - No '+', no spaces, no dashes
      - Includes country code

    Rules applied (in order):
      1. Strip whitespace, '+', '-', '(', ')'
      2. If the result is exactly 10 digits → prepend DEFAULT_COUNTRY_CODE (91)
      3. Return as-is otherwise (assume already has country code)
    """
    cleaned = number.strip().lstrip("+").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if len(cleaned) == 10 and cleaned.isdigit():
        cleaned = config.DEFAULT_COUNTRY_CODE + cleaned
    return cleaned


# ─── Timing Helpers ──────────────────────────────────────────────────────────

def random_delay(min_s: float | None = None, max_s: float | None = None) -> float:
    """
    Sleep for a random duration between min_s and max_s seconds.
    Also adds a tiny sub-second jitter to avoid machine-precision patterns.

    Returns the actual number of seconds slept.
    """
    low = min_s if min_s is not None else config.MIN_DELAY_SECONDS
    high = max_s if max_s is not None else config.MAX_DELAY_SECONDS
    duration = random.uniform(low, high)
    # Add sub-second jitter (0–500 ms) for extra unpredictability
    duration += random.uniform(0, 0.5)
    logger.debug("Sleeping %.2fs between messages (anti-detection delay)", duration)
    time.sleep(duration)
    return duration


def typing_duration(text: str) -> float:
    """
    Calculate a realistic composing-presence duration based on text length.

    Uses a simulated typing speed from config, clamped between
    MIN_COMPOSING_SECONDS and MAX_COMPOSING_SECONDS so very short or
    very long messages still look natural.
    """
    raw = len(text) / config.TYPING_CHARS_PER_SECOND
    # Add ±20% jitter to the raw typing time
    raw *= random.uniform(0.8, 1.2)
    clamped = max(config.MIN_COMPOSING_SECONDS, min(raw, config.MAX_COMPOSING_SECONDS))
    logger.debug("Composing presence duration: %.2fs for %d chars", clamped, len(text))
    return clamped


def media_presence_duration() -> float:
    """
    Return a random 'recording'/'uploading' presence duration for media messages.
    Media takes slightly longer to 'upload' than text takes to type.
    """
    return random.uniform(3.0, 8.0)


# ─── Presence Simulation ─────────────────────────────────────────────────────

def send_presence(number: str, presence: str = "composing") -> bool:
    """
    Tell Evolution API to show a presence indicator to the recipient.

    presence values:
      "composing"  → shows "typing..." in the chat
      "recording"  → shows "recording audio..." (looks natural for media)
      "paused"     → clears the presence indicator

    Returns True if the presence call succeeded, False otherwise.
    Does NOT raise — presence failure should never block the actual message.
    """
    url = f"{config.EVOLUTION_API_URL}/chat/updatePresence/{config.EVOLUTION_INSTANCE}"
    headers = {
        "apikey": config.EVOLUTION_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "number": number,
        "options": {
            "presence": presence,
        },
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=15)
        if resp.status_code in (200, 201):
            logger.debug("Presence '%s' set for %s", presence, number)
            return True
        else:
            logger.warning(
                "Presence update failed for %s — status %d: %s",
                number, resp.status_code, resp.text[:200],
            )
            return False
    except Exception as exc:
        logger.warning("Presence update exception for %s: %s", number, exc)
        return False


def simulate_human_text_sending(number: str, text: str) -> None:
    """
    Full human-behaviour lifecycle before sending a text message:
      1. Show "composing" presence
      2. Wait for realistic typing duration (proportional to message length)
      3. Clear presence (paused) — WhatsApp auto-clears after send anyway,
         but this step makes the session look cleaner
    """
    send_presence(number, "composing")
    duration = typing_duration(text)
    logger.info("Simulating typing for %.1fs (message: %d chars)", duration, len(text))
    time.sleep(duration)


def simulate_human_media_sending(number: str) -> None:
    """
    Full human-behaviour lifecycle before sending a media message:
      1. Show "recording" presence (looks like user is preparing media)
      2. Wait for realistic upload/preparation duration
    """
    send_presence(number, "recording")
    duration = media_presence_duration()
    logger.info("Simulating media upload presence for %.1fs", duration)
    time.sleep(duration)
