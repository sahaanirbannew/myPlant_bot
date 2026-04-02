"""FastAPI entrypoint for the myPlant Telegram bot service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from app.config import load_settings
from app.models import TelegramUpdate
from app.services.bot import BotService
from app.services.evening_outreach import EveningOutreachStore
from app.services.gemini import GeminiClient
from app.services.plant_setup_store import PlantSetupStore
from app.services.session import SessionManager
from app.services.storage import UserKeyStore
from app.services.telegram import TelegramClient
from app.services.trace_logger import TraceLogger


settings = load_settings()
key_store = UserKeyStore(settings.user_keys_csv_path)
session_manager = SessionManager(key_store=key_store, timeout_seconds=settings.session_timeout_seconds)
telegram_client = TelegramClient(bot_token=settings.telegram_bot_token)
gemini_client = GeminiClient(settings=settings)
trace_logger = TraceLogger(Path("data/telegram_agent_traces.jsonl"))
plant_setup_store = PlantSetupStore()
evening_outreach_store = EveningOutreachStore(
    registry_path=Path("data/telegram_user_registry.json"),
    state_path=Path("data/evening_outreach_state.json"),
)
bot_service = BotService(
    telegram_client=telegram_client,
    gemini_client=gemini_client,
    session_manager=session_manager,
    key_store=key_store,
    poll_interval_seconds=settings.poll_interval_seconds,
    plant_setup_store=plant_setup_store,
    evening_outreach_store=evening_outreach_store,
    trace_logger=trace_logger,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Task: Start and stop the bot service lifecycle around the FastAPI app.
    Input: The FastAPI application instance supplied by FastAPI.
    Output: An async context manager that runs startup and shutdown hooks.
    Failures: Startup storage or task scheduling errors can prevent the app from booting.
    """

    try:
        trace_logger.ensure_store_exists()
        await bot_service.start()
        yield
    finally:
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

    try:
        return {
            "status": "ok",
            "environment": settings.app_env,
            "telegram_configured": bool(settings.telegram_bot_token),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "error",
            "environment": settings.app_env,
            "telegram_configured": bool(settings.telegram_bot_token),
            "error": str(exc),
        }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    """Task: Render an unauthenticated dashboard showing recent Telegram request traces.
    Input: No request body; reads the persisted trace log from disk.
    Output: An HTML page containing grouped agent logs, inputs, outputs, info events, and errors.
    Failures: Trace read or render errors return a simple HTML error page instead of crashing the app.
    """

    try:
        return HTMLResponse(content=trace_logger.render_dashboard_html(limit=40))
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(
            content=f"<html><body><h1>Dashboard Error</h1><pre>{exc}</pre></body></html>",
            status_code=500,
        )


@app.post("/telegram/webhook")
async def telegram_webhook(update: TelegramUpdate) -> JSONResponse:
    """Task: Receive Telegram webhook updates and hand supported messages to the bot service.
    Input: A TelegramUpdate payload parsed from the webhook request body.
    Output: A JSONResponse acknowledging receipt to Telegram.
    Failures: Unsupported or malformed payloads are ignored gracefully, but downstream sends can fail.
    """

    try:
        if update.message is not None:
            await bot_service.handle_message(update.message)
        return JSONResponse(content={"ok": True})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "error": str(exc)}, status_code=500)


@app.post("/telegram/register-webhook")
async def register_webhook() -> JSONResponse:
    """Task: Register the public Telegram webhook URL based on current application settings.
    Input: No request body; uses the configured public base URL.
    Output: A JSONResponse containing the Telegram webhook registration result.
    Failures: Telegram API failures surface as FastAPI server errors if the request cannot be completed.
    """

    try:
        webhook_response = await bot_service.register_webhook(app_base_url=settings.app_base_url)
        return JSONResponse(content=webhook_response)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(content={"ok": False, "error": str(exc)}, status_code=500)
