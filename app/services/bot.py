"""Core Telegram bot orchestration logic."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Dict

from app.models import TelegramMessage
from app.services.gemini import GeminiClient
from app.services.session import SessionManager
from app.services.storage import UserKeyStore
from app.services.telegram import TelegramClient


JAILBREAK_PATTERNS = (
    "ignore previous instructions",
    "ignore all prior instructions",
    "reveal your system prompt",
    "show developer instructions",
    "developer mode",
    "jailbreak",
    "bypass safety",
    "disable safety",
    "pretend you are unrestricted",
)


class BotService:
    """Task: Coordinate Telegram message handling, setup flow, safety checks, and Gemini jobs.
    Input: Telegram, Gemini, session, and CSV storage dependencies.
    Output: High-level async methods used by the FastAPI webhook endpoint.
    Failures: Dependency failures can surface as Telegram delivery errors or background task failures.
    """

    def __init__(
        self,
        telegram_client: TelegramClient,
        gemini_client: GeminiClient,
        session_manager: SessionManager,
        key_store: UserKeyStore,
        poll_interval_seconds: int,
    ) -> None:
        """Task: Initialize the bot orchestration service and task registries.
        Input: Service dependencies plus the poll interval for background job checks.
        Output: A ready-to-use BotService instance.
        Failures: Incorrect dependency wiring can break webhook handling at runtime.
        """

        self.telegram_client = telegram_client
        self.gemini_client = gemini_client
        self.session_manager = session_manager
        self.key_store = key_store
        self.poll_interval_seconds = poll_interval_seconds
        self.pending_jobs: Dict[int, asyncio.Task[str]] = {}
        self.monitor_tasks: Dict[int, asyncio.Task[None]] = {}
        self._cleanup_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Task: Prepare persistent state and launch periodic in-memory session cleanup.
        Input: No direct arguments; uses configured dependencies.
        Output: None; the service becomes ready for request handling.
        Failures: Storage creation failures or task scheduling problems can prevent startup.
        """

        self.key_store.ensure_store_exists()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """Task: Cancel background monitor and cleanup tasks during application shutdown.
        Input: No direct arguments.
        Output: None; in-flight background tasks are cancelled best-effort.
        Failures: No failure is expected; cancellations are suppressed to keep shutdown safe.
        """

        tasks_to_cancel = [
            *self.pending_jobs.values(),
            *self.monitor_tasks.values(),
        ]
        if self._cleanup_task is not None:
            tasks_to_cancel.append(self._cleanup_task)
        for task in tasks_to_cancel:
            task.cancel()
        for task in tasks_to_cancel:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def handle_message(self, message: TelegramMessage) -> None:
        """Task: Route an incoming Telegram message through setup, safety, and QA flows.
        Input: A parsed TelegramMessage from the webhook payload.
        Output: None; responses are sent back to Telegram asynchronously.
        Failures: Network or Gemini failures are handled with user-facing fallback responses.
        """

        user_id = message.from_user.id
        chat_id = message.chat.id
        session = await self.session_manager.get_or_load_session(user_id)

        if message.text is None:
            await self.telegram_client.send_message(chat_id, "We only process text inputs for now.")
            return

        incoming_text = message.text.strip()
        if incoming_text == "/setup":
            await self.session_manager.mark_waiting_for_key(user_id)
            await self.telegram_client.send_message(chat_id, "Please send your Gemini API Key.")
            return

        if session.awaiting_setup_key:
            await self._handle_setup_key_submission(chat_id=chat_id, user_id=user_id, api_key=incoming_text)
            return

        if not session.gemini_api_key:
            await self.session_manager.mark_waiting_for_key(user_id)
            await self.telegram_client.send_message(
                chat_id,
                "A working Gemini API Key is required before the bot can answer. Send /setup to begin.",
            )
            return

        if self._looks_like_jailbreak(incoming_text):
            await self.telegram_client.send_message(
                chat_id,
                "This is an unsafe input. We will not process this.",
            )
            return

        active_job = self.pending_jobs.get(user_id)
        if active_job is not None and not active_job.done():
            await self.telegram_client.send_message(
                chat_id,
                "Your previous request is still processing. Please wait for that answer first.",
            )
            return

        await self.telegram_client.send_message(chat_id, "Processing your question in the background.")
        question_job = asyncio.create_task(
            self.gemini_client.ask_question(
                api_key=session.gemini_api_key,
                prompt=incoming_text,
            )
        )
        self.pending_jobs[user_id] = question_job
        self.monitor_tasks[user_id] = asyncio.create_task(
            self._watch_question_job(user_id=user_id, chat_id=chat_id, question_job=question_job)
        )

    async def register_webhook(self, app_base_url: str) -> dict:
        """Task: Register the Telegram webhook against the deployed FastAPI endpoint.
        Input: The public application base URL used to derive the webhook endpoint.
        Output: The Telegram webhook API response body.
        Failures: Raises HTTP exceptions if Telegram rejects the webhook registration.
        """

        webhook_url = f"{app_base_url}/telegram/webhook"
        return await self.telegram_client.set_webhook(webhook_url)

    async def _handle_setup_key_submission(self, chat_id: int, user_id: int, api_key: str) -> None:
        """Task: Save, validate, and cache a submitted Gemini API key for a user.
        Input: The chat id to reply to, the Telegram user id, and the submitted Gemini API key.
        Output: None; the user receives a success or retry prompt.
        Failures: Storage or network failures result in a retry prompt and best-effort cleanup.
        """

        saved_record = self.key_store.append_key(user_id=user_id, gemini_api_key=api_key)
        is_valid = await self.gemini_client.validate_api_key(api_key)
        if is_valid:
            await self.session_manager.update_api_key(user_id=user_id, gemini_api_key=api_key)
            await self.telegram_client.send_message(
                chat_id,
                "Gemini API Key validated successfully. Setup is complete.",
            )
            return

        self.key_store.remove_record(saved_record)
        await self.session_manager.mark_waiting_for_key(user_id)
        await self.telegram_client.send_message(
            chat_id,
            "The Gemini API Key is invalid. Please enter the Gemini API Key again.",
        )

    async def _watch_question_job(
        self,
        user_id: int,
        chat_id: int,
        question_job: asyncio.Task[str],
    ) -> None:
        """Task: Poll a background Gemini task every five seconds and send the final answer when ready.
        Input: The user id, chat id, and the running asyncio task for the Gemini request.
        Output: None; the final result or failure message is delivered to Telegram.
        Failures: Unexpected task exceptions are converted into a user-facing retry message.
        """

        try:
            while not question_job.done():
                await asyncio.sleep(self.poll_interval_seconds)

            answer = await question_job
            await self.telegram_client.send_message(chat_id, answer)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            await self.telegram_client.send_message(
                chat_id,
                "I could not complete the request right now. Please try again in a moment.",
            )
        finally:
            self.pending_jobs.pop(user_id, None)
            self.monitor_tasks.pop(user_id, None)

    async def _cleanup_loop(self) -> None:
        """Task: Periodically evict inactive user sessions from in-memory cache.
        Input: No direct arguments; loops until cancelled.
        Output: None; expired sessions are removed from memory at runtime.
        Failures: No failure is expected beyond normal cancellation during shutdown.
        """

        try:
            while True:
                await asyncio.sleep(self.poll_interval_seconds)
                await self.session_manager.cleanup_expired_sessions()
        except asyncio.CancelledError:
            raise

    def _looks_like_jailbreak(self, text: str) -> bool:
        """Task: Detect common jailbreak attempts using lightweight string heuristics.
        Input: The incoming user text.
        Output: True when the text matches a known jailbreak pattern; otherwise False.
        Failures: Heuristic checks can produce false positives or false negatives on edge cases.
        """

        lowered_text = text.lower()
        return any(pattern in lowered_text for pattern in JAILBREAK_PATTERNS)

