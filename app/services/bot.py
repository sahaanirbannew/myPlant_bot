"""Core Telegram bot orchestration logic."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any, Dict

from app.models import TelegramMessage
from app.services.gemini import GeminiClient
from app.services.session import SessionManager
from app.services.storage import UserKeyStore
from app.services.telegram import TelegramClient
from app.services.trace_logger import TraceLogger


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
        trace_logger: TraceLogger | None = None,
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
        self.trace_logger = trace_logger

    async def start(self) -> None:
        """Task: Prepare persistent state and launch periodic in-memory session cleanup.
        Input: No direct arguments; uses configured dependencies.
        Output: None; the service becomes ready for request handling.
        Failures: Storage creation failures or task scheduling problems can prevent startup.
        """

        try:
            self.key_store.ensure_store_exists()
            if self.trace_logger is not None:
                self.trace_logger.ensure_store_exists()
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        except Exception:
            raise

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

        trace_id = self._new_trace_id()
        user_id = message.from_user.id
        chat_id = message.chat.id

        try:
            self._log_trace(
                trace_id=trace_id,
                level="info",
                agent="telegram_input_agent",
                message="Received Telegram message.",
                user_id=user_id,
                chat_id=chat_id,
                telegram_text=message.text,
                agent_input={"message_id": getattr(message, "message_id", None), "text": message.text},
                agent_output="Webhook payload accepted.",
            )

            session = await self.session_manager.get_or_load_session(user_id)
            self._log_trace(
                trace_id=trace_id,
                level="info",
                agent="session_agent",
                message="Loaded user session.",
                user_id=user_id,
                chat_id=chat_id,
                telegram_text=message.text,
                agent_input={"user_id": user_id},
                agent_output={
                    "awaiting_setup_key": session.awaiting_setup_key,
                    "has_gemini_api_key": bool(session.gemini_api_key),
                },
            )

            if message.text is None:
                await self._send_and_log(
                    trace_id=trace_id,
                    chat_id=chat_id,
                    text="We only process text inputs for now.",
                    user_id=user_id,
                    telegram_text=None,
                    reason="Rejected non-text input.",
                )
                return

            incoming_text = message.text.strip()
            if incoming_text == "/setup":
                await self.session_manager.mark_waiting_for_key(user_id)
                self._log_trace(
                    trace_id=trace_id,
                    level="info",
                    agent="setup_agent",
                    message="Entered setup flow.",
                    user_id=user_id,
                    chat_id=chat_id,
                    telegram_text=incoming_text,
                    agent_input=incoming_text,
                    agent_output="User marked as waiting for Gemini API key.",
                )
                await self._send_and_log(
                    trace_id=trace_id,
                    chat_id=chat_id,
                    text="Please send your Gemini API Key.",
                    user_id=user_id,
                    telegram_text=incoming_text,
                    reason="Requested Gemini API key.",
                )
                return

            if session.awaiting_setup_key:
                await self._handle_setup_key_submission(
                    trace_id=trace_id,
                    chat_id=chat_id,
                    user_id=user_id,
                    api_key=incoming_text,
                )
                return

            if not session.gemini_api_key:
                await self.session_manager.mark_waiting_for_key(user_id)
                self._log_trace(
                    trace_id=trace_id,
                    level="info",
                    agent="setup_agent",
                    message="No Gemini API key available for the user.",
                    user_id=user_id,
                    chat_id=chat_id,
                    telegram_text=incoming_text,
                    agent_input={"user_id": user_id},
                    agent_output="User redirected to setup.",
                )
                await self._send_and_log(
                    trace_id=trace_id,
                    chat_id=chat_id,
                    text="A working Gemini API Key is required before the bot can answer. Send /setup to begin.",
                    user_id=user_id,
                    telegram_text=incoming_text,
                    reason="Blocked request until setup is complete.",
                )
                return

            if self._looks_like_jailbreak(incoming_text):
                self._log_trace(
                    trace_id=trace_id,
                    level="info",
                    agent="safety_agent",
                    message="Blocked unsafe prompt.",
                    user_id=user_id,
                    chat_id=chat_id,
                    telegram_text=incoming_text,
                    agent_input=incoming_text,
                    agent_output="Detected jailbreak-like pattern.",
                )
                await self._send_and_log(
                    trace_id=trace_id,
                    chat_id=chat_id,
                    text="This is an unsafe input. We will not process this.",
                    user_id=user_id,
                    telegram_text=incoming_text,
                    reason="Safety filter response sent.",
                )
                return

            active_job = self.pending_jobs.get(user_id)
            if active_job is not None and not active_job.done():
                self._log_trace(
                    trace_id=trace_id,
                    level="info",
                    agent="queue_agent",
                    message="Rejected overlapping request.",
                    user_id=user_id,
                    chat_id=chat_id,
                    telegram_text=incoming_text,
                    agent_input=incoming_text,
                    agent_output="Previous background job still processing.",
                )
                await self._send_and_log(
                    trace_id=trace_id,
                    chat_id=chat_id,
                    text="Your previous request is still processing. Please wait for that answer first.",
                    user_id=user_id,
                    telegram_text=incoming_text,
                    reason="Queue backpressure notice sent.",
                )
                return

            self._log_trace(
                trace_id=trace_id,
                level="info",
                agent="gemini_agent",
                message="Queued Gemini background job.",
                user_id=user_id,
                chat_id=chat_id,
                telegram_text=incoming_text,
                agent_input=incoming_text,
                agent_output="Background task created.",
            )
            question_job = asyncio.create_task(
                self._run_question_job(
                    trace_id=trace_id,
                    api_key=session.gemini_api_key,
                    prompt=incoming_text,
                    user_id=user_id,
                    chat_id=chat_id,
                )
            )
            self.pending_jobs[user_id] = question_job
            self.monitor_tasks[user_id] = asyncio.create_task(
                self._watch_question_job(
                    trace_id=trace_id,
                    user_id=user_id,
                    chat_id=chat_id,
                    telegram_text=incoming_text,
                    question_job=question_job,
                )
            )
        except Exception as exc:  # noqa: BLE001
            self._log_trace(
                trace_id=trace_id,
                level="error",
                agent="bot_service",
                message="Unhandled error while processing Telegram message.",
                user_id=user_id,
                chat_id=chat_id,
                telegram_text=message.text,
                agent_input={"text": message.text},
                error=str(exc),
            )
            await self._safe_send_fallback(chat_id=chat_id)

    async def register_webhook(self, app_base_url: str) -> dict:
        """Task: Register the Telegram webhook against the deployed FastAPI endpoint.
        Input: The public application base URL used to derive the webhook endpoint.
        Output: The Telegram webhook API response body.
        Failures: Raises HTTP exceptions if Telegram rejects the webhook registration.
        """

        webhook_url = f"{app_base_url}/telegram/webhook"
        return await self.telegram_client.set_webhook(webhook_url)

    async def _handle_setup_key_submission(self, trace_id: str, chat_id: int, user_id: int, api_key: str) -> None:
        """Task: Save, validate, and cache a submitted Gemini API key for a user.
        Input: The chat id to reply to, the Telegram user id, and the submitted Gemini API key.
        Output: None; the user receives a success or retry prompt.
        Failures: Storage or network failures result in a retry prompt and best-effort cleanup.
        """

        try:
            masked_key = self._mask_api_key(api_key)
            self._log_trace(
                trace_id=trace_id,
                level="info",
                agent="setup_agent",
                message="Received Gemini API key submission.",
                user_id=user_id,
                chat_id=chat_id,
                telegram_text="[setup key submission]",
                agent_input={"masked_api_key": masked_key},
                agent_output="Stored submitted key for validation.",
            )

            saved_record = self.key_store.append_key(user_id=user_id, gemini_api_key=api_key)
            is_valid = await self.gemini_client.validate_api_key(api_key)
            self._log_trace(
                trace_id=trace_id,
                level="info",
                agent="gemini_validation_agent",
                message="Completed Gemini API key validation.",
                user_id=user_id,
                chat_id=chat_id,
                telegram_text="[setup key submission]",
                agent_input={"masked_api_key": masked_key},
                agent_output={"is_valid": is_valid},
            )
            if is_valid:
                await self.session_manager.update_api_key(user_id=user_id, gemini_api_key=api_key)
                await self._send_and_log(
                    trace_id=trace_id,
                    chat_id=chat_id,
                    text="Gemini API Key validated successfully. Setup is complete.",
                    user_id=user_id,
                    telegram_text="[setup key submission]",
                    reason="Setup completion message sent.",
                )
                return

            self.key_store.remove_record(saved_record)
            await self.session_manager.mark_waiting_for_key(user_id)
            await self._send_and_log(
                trace_id=trace_id,
                chat_id=chat_id,
                text="The Gemini API Key is invalid. Please enter the Gemini API Key again.",
                user_id=user_id,
                telegram_text="[setup key submission]",
                reason="Setup retry prompt sent.",
            )
        except Exception as exc:  # noqa: BLE001
            self._log_trace(
                trace_id=trace_id,
                level="error",
                agent="setup_agent",
                message="Failed to process Gemini API key submission.",
                user_id=user_id,
                chat_id=chat_id,
                telegram_text="[setup key submission]",
                agent_input={"masked_api_key": self._mask_api_key(api_key)},
                error=str(exc),
            )
            await self._send_and_log(
                trace_id=trace_id,
                chat_id=chat_id,
                text="I could not validate the Gemini API Key right now. Please try again.",
                user_id=user_id,
                telegram_text="[setup key submission]",
                reason="Setup error response sent.",
            )

    async def _run_question_job(
        self,
        trace_id: str,
        api_key: str,
        prompt: str,
        user_id: int,
        chat_id: int,
    ) -> str:
        """Task: Execute one Gemini question job while logging the agent input and output.
        Input: The trace id, Gemini API key, user prompt, and request metadata.
        Output: The raw Gemini answer text for downstream formatting and delivery.
        Failures: Gemini request errors are re-raised after being logged.
        """

        try:
            answer = await self.gemini_client.ask_question(api_key=api_key, prompt=prompt)
            self._log_trace(
                trace_id=trace_id,
                level="info",
                agent="gemini_agent",
                message="Gemini background job completed.",
                user_id=user_id,
                chat_id=chat_id,
                telegram_text=prompt,
                agent_input=prompt,
                agent_output=answer,
            )
            return answer
        except Exception as exc:  # noqa: BLE001
            self._log_trace(
                trace_id=trace_id,
                level="error",
                agent="gemini_agent",
                message="Gemini background job failed.",
                user_id=user_id,
                chat_id=chat_id,
                telegram_text=prompt,
                agent_input=prompt,
                error=str(exc),
            )
            raise

    async def _watch_question_job(
        self,
        trace_id: str,
        user_id: int,
        chat_id: int,
        telegram_text: str,
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
            formatted_answer = self._format_answer_for_telegram(answer)
            await self._send_and_log(
                trace_id=trace_id,
                chat_id=chat_id,
                text=formatted_answer,
                user_id=user_id,
                telegram_text=telegram_text,
                reason="Delivered final Gemini answer to Telegram.",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._log_trace(
                trace_id=trace_id,
                level="error",
                agent="delivery_agent",
                message="Failed while monitoring or delivering Gemini answer.",
                user_id=user_id,
                chat_id=chat_id,
                telegram_text=telegram_text,
                error=str(exc),
            )
            await self._send_and_log(
                trace_id=trace_id,
                chat_id=chat_id,
                text="I could not complete the request right now. Please try again in a moment.",
                user_id=user_id,
                telegram_text=telegram_text,
                reason="Delivered fallback error message to Telegram.",
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

    def _format_answer_for_telegram(self, answer: str) -> str:
        """Task: Normalize model output so Telegram users receive plain text without bold markers.
        Input: The raw text returned by the Gemini model.
        Output: A sanitized Telegram-safe response string.
        Failures: Unexpected non-string values can raise attribute errors before the text is sent.
        """

        return answer.replace("**", "").strip()

    async def _send_and_log(
        self,
        trace_id: str,
        chat_id: int,
        text: str,
        user_id: int,
        telegram_text: str | None,
        reason: str,
    ) -> None:
        """Task: Send a Telegram message and record the delivery event in the trace log.
        Input: Trace metadata, outbound chat id, reply text, and a short reason for the send.
        Output: None; the message is sent to Telegram and logged.
        Failures: Telegram delivery errors are logged and then re-raised.
        """

        try:
            await self.telegram_client.send_message(chat_id, text)
            self._log_trace(
                trace_id=trace_id,
                level="info",
                agent="telegram_output_agent",
                message=reason,
                user_id=user_id,
                chat_id=chat_id,
                telegram_text=telegram_text,
                agent_input={"chat_id": chat_id},
                agent_output=text,
            )
        except Exception as exc:  # noqa: BLE001
            self._log_trace(
                trace_id=trace_id,
                level="error",
                agent="telegram_output_agent",
                message="Failed to send message to Telegram.",
                user_id=user_id,
                chat_id=chat_id,
                telegram_text=telegram_text,
                agent_input={"chat_id": chat_id, "text": text},
                error=str(exc),
            )
            raise

    async def _safe_send_fallback(self, chat_id: int) -> None:
        """Task: Best-effort send a generic fallback message after an internal bot error.
        Input: The Telegram chat id that should receive the fallback reply.
        Output: None; failures are suppressed to avoid cascading errors.
        Failures: No failure is expected because send errors are suppressed.
        """

        with contextlib.suppress(Exception):
            await self.telegram_client.send_message(
                chat_id,
                "Something went wrong on my side. Please try again in a moment.",
            )

    def _new_trace_id(self) -> str:
        """Task: Produce a new trace id for one Telegram request flow.
        Input: No direct arguments.
        Output: A unique trace id string.
        Failures: No failure is expected.
        """

        if self.trace_logger is None:
            return "no-trace"
        return self.trace_logger.new_trace_id()

    def _log_trace(
        self,
        trace_id: str,
        level: str,
        agent: str,
        message: str,
        user_id: int | None,
        chat_id: int | None,
        telegram_text: str | None,
        agent_input: Any | None = None,
        agent_output: Any | None = None,
        error: str | None = None,
    ) -> None:
        """Task: Append a structured trace event when dashboard logging is enabled.
        Input: Trace metadata plus optional input, output, and error payloads.
        Output: None; the event is written to the trace log if a logger is configured.
        Failures: Trace logging failures are suppressed so observability cannot break the bot flow.
        """

        if self.trace_logger is None:
            return
        with contextlib.suppress(Exception):
            self.trace_logger.log_event(
                trace_id=trace_id,
                level=level,
                agent=agent,
                message=message,
                user_id=user_id,
                chat_id=chat_id,
                telegram_text=telegram_text,
                agent_input=agent_input,
                agent_output=agent_output,
                error=error,
            )

    def _mask_api_key(self, api_key: str) -> str:
        """Task: Reduce an API key to a masked form before it is written to logs.
        Input: The raw Gemini API key string.
        Output: A masked key string safe for dashboard display.
        Failures: No failure is expected.
        """

        trimmed = api_key.strip()
        if len(trimmed) <= 8:
            return "*" * len(trimmed)
        return f"{trimmed[:4]}...{trimmed[-4:]}"
