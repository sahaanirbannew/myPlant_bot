"""Configuration helpers for the myPlant bot service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    """Task: Store application configuration loaded from environment variables.
    Input: Environment variables and optional values from the local .env file.
    Output: An immutable settings object used across the application.
    Failures: May produce incorrect runtime behavior if required variables are missing or malformed.
    """

    app_env: str
    app_host: str
    app_port: int
    app_base_url: str
    telegram_bot_token: str
    telegram_bot_username: str
    gemini_model: str
    gemini_api_base_url: str
    user_keys_csv_path: Path
    session_timeout_seconds: int
    poll_interval_seconds: int
    max_gemini_retries: int
    retry_delay_seconds: int


def _get_int(name: str, default: int) -> int:
    """Task: Read an integer environment variable with a safe default.
    Input: The environment variable name and the default integer value.
    Output: The parsed integer value or the provided default.
    Failures: Raises ValueError if the variable is set but cannot be parsed as an integer.
    """

    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return int(raw_value)


def load_settings() -> Settings:
    """Task: Build the application settings object from the environment.
    Input: No direct function arguments; reads process environment variables.
    Output: A populated Settings instance ready for dependency wiring.
    Failures: Raises ValueError if integer configuration values are malformed.
    """

    return Settings(
        app_env=os.getenv("APP_ENV", "development"),
        app_host=os.getenv("APP_HOST", "0.0.0.0"),
        app_port=_get_int("APP_PORT", 8000),
        app_base_url=os.getenv("APP_BASE_URL", "https://your-domain.example.com").rstrip("/"),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        telegram_bot_username=os.getenv("TELEGRAM_BOT_USERNAME", "@your_bot_username").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip(),
        gemini_api_base_url=os.getenv(
            "GEMINI_API_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        ).rstrip("/"),
        user_keys_csv_path=Path(os.getenv("USER_KEYS_CSV_PATH", "data/user_gemini_keys.csv")),
        session_timeout_seconds=_get_int("SESSION_TIMEOUT_SECONDS", 180),
        poll_interval_seconds=_get_int("POLL_INTERVAL_SECONDS", 5),
        max_gemini_retries=_get_int("MAX_GEMINI_RETRIES", 5),
        retry_delay_seconds=_get_int("RETRY_DELAY_SECONDS", 2),
    )

