"""
config.py — Central configuration for the WhatsApp microservice.
All environment variables are loaded and validated here.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── Evolution API ───────────────────────────────────────────────────────────
EVOLUTION_API_URL: str = os.getenv("EVOLUTION_API_URL", "").strip().rstrip("/")
EVOLUTION_API_KEY: str = os.getenv("EVOLUTION_API_KEY", "").strip()
EVOLUTION_INSTANCE: str = os.getenv("EVOLUTION_INSTANCE", "").strip()

# ─── This Server ─────────────────────────────────────────────────────────────
# Secret token that the main backend must supply in every request header
# Header name: X-WA-Secret
WA_SERVER_SECRET: str = os.getenv("WA_SERVER_SECRET", "change-me-in-production")

# Port this Flask service listens on
PORT: int = int(os.getenv("PORT", "5055"))

# ─── Anti-Detection / Timing ──────────────────────────────────────────────────
# Minimum and maximum seconds to wait between consecutive messages
# (random value is picked in this range for each message)
MIN_DELAY_SECONDS: float = float(os.getenv("MIN_DELAY_SECONDS", "8"))
MAX_DELAY_SECONDS: float = float(os.getenv("MAX_DELAY_SECONDS", "25"))

# Simulated typing speed (characters per second) — used to calculate
# how long to show "composing" before sending a text message
TYPING_CHARS_PER_SECOND: float = float(os.getenv("TYPING_CHARS_PER_SECOND", "7"))

# Minimum / maximum composing presence duration in seconds
MIN_COMPOSING_SECONDS: float = float(os.getenv("MIN_COMPOSING_SECONDS", "2"))
MAX_COMPOSING_SECONDS: float = float(os.getenv("MAX_COMPOSING_SECONDS", "12"))

# ─── Retry ───────────────────────────────────────────────────────────────────
MAX_RETRIES: int = int(os.getenv("MAX_RETRIES", "3"))
RETRY_BASE_DELAY: float = float(os.getenv("RETRY_BASE_DELAY", "5"))  # seconds

# ─── Phone Number ────────────────────────────────────────────────────────────
# Default country code prefix added to 10-digit numbers (India = 91)
DEFAULT_COUNTRY_CODE: str = os.getenv("DEFAULT_COUNTRY_CODE", "91")

# ─── Validation ──────────────────────────────────────────────────────────────
def validate_config() -> None:
    """Called at startup — raises ValueError if critical vars are missing."""
    missing = []
    if not EVOLUTION_API_URL:
        missing.append("EVOLUTION_API_URL")
    if not EVOLUTION_API_KEY:
        missing.append("EVOLUTION_API_KEY")
    if not EVOLUTION_INSTANCE:
        missing.append("EVOLUTION_INSTANCE")
    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Please set them in your .env file or deployment environment."
        )
