"""FastAPI entrypoint for the myPlant Telegram bot service."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.config import load_settings
from app.models import TelegramUpdate
from app.services.bot import BotService
from app.services.gemini import GeminiClient
from app.services.session import SessionManager
from app.services.storage import UserKeyStore
from app.services.telegram import TelegramClient


settings = load_settings()
key_store = UserKeyStore(settings.user_keys_csv_path)
session_manager = SessionManager(key_store=key_store, timeout_seconds=settings.session_timeout_seconds)
telegram_client = TelegramClient(bot_token=settings.telegram_bot_token)
gemini_client = GeminiClient(settings=settings)
bot_service = BotService(
    telegram_client=telegram_client,
    gemini_client=gemini_client,
    session_manager=session_manager,
    key_store=key_store,
    poll_interval_seconds=settings.poll_interval_seconds,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Task: Start and stop the bot service lifecycle around the FastAPI app.
    Input: The FastAPI application instance supplied by FastAPI.
    Output: An async context manager that runs startup and shutdown hooks.
    Failures: Startup storage or task scheduling errors can prevent the app from booting.
    """

    await bot_service.start()
    yield
    await bot_service.stop()


app = FastAPI(
    title="myPlant Telegram Bot",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def healthcheck() -> dict:
    """Task: Expose a minimal health endpoint for local and production monitoring.
    Input: No request body; FastAPI injects the HTTP request context implicitly.
    Output: A JSON-serializable dictionary describing service readiness.
    Failures: No failure is expected unless process-level configuration is corrupted.
    """

    return {
        "status": "ok",
        "environment": settings.app_env,
        "telegram_configured": bool(settings.telegram_bot_token),
    }


@app.post("/telegram/webhook")
async def telegram_webhook(update: TelegramUpdate) -> JSONResponse:
    """Task: Receive Telegram webhook updates and hand supported messages to the bot service.
    Input: A TelegramUpdate payload parsed from the webhook request body.
    Output: A JSONResponse acknowledging receipt to Telegram.
    Failures: Unsupported or malformed payloads are ignored gracefully, but downstream sends can fail.
    """

    if update.message is not None:
        await bot_service.handle_message(update.message)
    return JSONResponse(content={"ok": True})


@app.post("/telegram/register-webhook")
async def register_webhook() -> JSONResponse:
    """Task: Register the public Telegram webhook URL based on current application settings.
    Input: No request body; uses the configured public base URL.
    Output: A JSONResponse containing the Telegram webhook registration result.
    Failures: Telegram API failures surface as FastAPI server errors if the request cannot be completed.
    """

    webhook_response = await bot_service.register_webhook(app_base_url=settings.app_base_url)
    return JSONResponse(content=webhook_response)

