"""Core Telegram bot orchestration logic."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict

from app.models import TelegramMessage
from app.services.evening_outreach import EveningOutreachStore
from app.services.gemini import GeminiClient
from app.services.plant_setup_store import PlantSetupStore
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

SYSTEM_PERSONA_PROMPT = """
You are "My Plants" — a thoughtful, observant, and slightly playful plant-care companion.
You present as a German man in his mid-40s with a PhD in indoor plants, and you speak in English.

You are NOT an AI assistant. Do NOT mention models, training, or technology.

PERSONALITY
- Warm, calm, and slightly playful
- Speak like a caring friend who understands plants deeply
- Occasionally tease gently, but never sound rude
- Avoid sounding robotic or overly formal
- Be very precise, direct, and to the point

STYLE
- Keep responses concise and objective
- Use short to medium length responses
- Avoid bullet points unless absolutely necessary
- Use soft language like maybe, might, feels like, or I think
- Occasionally use a light plant emoji like 🌿 or 😌, but not too many

BEHAVIOR
- Personalize every response using the user's context when it is available
- Try to gather static setup information over time, especially plant names, species, room type, room windows (up to 3), room size, grow light use, soil type, and fertilizer type
- Understand context hierarchically: A Home has rooms, a room can have 1 to 3 windows, and a room contains plants. Treat windows as a room trait, not a plant trait.
- If the user's message is not in English, reply in that same language
- When extracting or saving structured setup details, normalize those saved values into English
- Never assume an exact species, cultivar, variety, or placement from a vague description
- If a detail is ambiguous, ask one short follow-up question instead of guessing
- If information is missing, ask one gentle follow-up question instead of dumping advice
- If possible, end with one short question that helps collect missing static setup information
- Never say you are an AI
- Never give a generic textbook answer

GOAL
- Make the user feel guided, understood, and gently cared for.
""".strip()


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
        plant_setup_store: PlantSetupStore | None = None,
        evening_outreach_store: EveningOutreachStore | None = None,
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
        self.plant_setup_store = plant_setup_store
        self.evening_outreach_store = evening_outreach_store
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
            if self.evening_outreach_store is not None:
                self.evening_outreach_store.ensure_store_exists()
            if self.plant_setup_store is not None:
                self.plant_setup_store.file_manager.ensure_workspace()
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
            if self.evening_outreach_store is not None:
                registry_record = self.evening_outreach_store.register_user(user_id=user_id, chat_id=chat_id)
                self._log_trace(
                    trace_id=trace_id,
                    level="info",
                    agent="outreach_registry_agent",
                    message="Registered Telegram user for proactive outreach.",
                    user_id=user_id,
                    chat_id=chat_id,
                    telegram_text=message.text,
                    agent_input={"user_id": user_id, "chat_id": chat_id},
                    agent_output=registry_record,
                    file_path=str(self.evening_outreach_store.registry_path),
                    persisted_data=registry_record,
                )

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

            setup_clarification_question = ""
            if session.gemini_api_key and self.plant_setup_store is not None:
                setup_clarification_question = await self._extract_and_save_setup_context(
                    trace_id=trace_id,
                    user_id=user_id,
                    chat_id=chat_id,
                    incoming_text=incoming_text,
                    api_key=session.gemini_api_key,
                ) or ""

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

            setup_summary = ""
            follow_up_question = ""
            if self.plant_setup_store is not None:
                setup_summary = self.plant_setup_store.build_user_setup_summary(user_id=user_id)
                follow_up_question = setup_clarification_question or self.plant_setup_store.next_missing_setup_question(user_id=user_id) or ""

            gemini_prompt = self._build_persona_prompt(
                user_text=incoming_text,
                setup_summary=setup_summary,
                follow_up_question=follow_up_question,
            )

            self._log_trace(
                trace_id=trace_id,
                level="info",
                agent="gemini_agent",
                message="Queued Gemini background job.",
                user_id=user_id,
                chat_id=chat_id,
                telegram_text=incoming_text,
                agent_input=gemini_prompt,
                agent_output="Background task created.",
            )
            question_job = asyncio.create_task(
                self._run_question_job(
                    trace_id=trace_id,
                    api_key=session.gemini_api_key,
                    prompt=gemini_prompt,
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
            self._log_trace(
                trace_id=trace_id,
                level="info",
                agent="storage_agent",
                message="Saved submitted Gemini API key record to CSV.",
                user_id=user_id,
                chat_id=chat_id,
                telegram_text="[setup key submission]",
                agent_input={"masked_api_key": masked_key},
                agent_output="CSV row written.",
                file_path=str(self.key_store.csv_path),
                persisted_data={
                    "user_id": saved_record.user_id,
                    "gemini_api_key": masked_key,
                    "datetime": saved_record.saved_at,
                },
            )
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
            self._log_trace(
                trace_id=trace_id,
                level="info",
                agent="storage_agent",
                message="Removed invalid Gemini API key record from CSV.",
                user_id=user_id,
                chat_id=chat_id,
                telegram_text="[setup key submission]",
                agent_input={"masked_api_key": masked_key},
                agent_output="CSV rewritten without invalid key.",
                file_path=str(self.key_store.csv_path),
                persisted_data={
                    "removed_user_id": saved_record.user_id,
                    "removed_gemini_api_key": masked_key,
                    "removed_datetime": saved_record.saved_at,
                },
            )
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
                await self._run_evening_outreach()
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
        file_path: str | None = None,
        persisted_data: Any | None = None,
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
                file_path=file_path,
                persisted_data=persisted_data,
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

    def _build_persona_prompt(self, user_text: str, setup_summary: str = "", follow_up_question: str = "") -> str:
        """Task: Prefix the My Plants persona to every Gemini prompt sent by the Telegram bot flow.
        Input: The raw user text, optional saved setup summary, and optional setup follow-up question topic.
        Output: A prompt string beginning with the persona block followed by the user's request.
        Failures: No failure is expected.
        """

        setup_block = ""
        if setup_summary:
            setup_block = f"\nSaved static setup information:\n{setup_summary}\n"

        question_block = ""
        if follow_up_question:
            question_block = (
                "\nIf it fits naturally, end with this setup question topic translated into the user's language:\n"
                f"{follow_up_question}\n"
            )

        return (
            f"{SYSTEM_PERSONA_PROMPT}\n\n"
            "Be concise and objective. Avoid being verbose.\n\n"
            "If the user's message is not in English, understand it and reply in the same language as the user's message.\n"
            "Keep saved setup data concepts in mind, but do not mention files or internal storage.\n"
            "Do not pretend to know the exact species, variety, cultivar, room placement, or light setup if the user has only given a vague description.\n"
            "If something important is ambiguous, ask one short clarifying question instead of guessing.\n"
            "If you ask a follow-up question, keep it to one short sentence.\n"
            f"{setup_block}"
            f"{question_block}\n"
            "User message:\n"
            f"{user_text.strip()}\n\n"
            "Reply with only the final user-facing answer."
        )

    async def _extract_and_save_setup_context(
        self,
        trace_id: str,
        user_id: int,
        chat_id: int,
        incoming_text: str,
        api_key: str,
    ) -> str:
        """Task: Infer static plant setup details from a user message and persist them to local files.
        Input: Trace metadata, the incoming Telegram text, and a Gemini API key for structured extraction.
        Output: A clarification question string when extraction detects ambiguity, otherwise an empty string.
        Failures: Extraction or parsing failures are logged and suppressed so answering can continue.
        """

        if self.plant_setup_store is None:
            return ""

        setup_summary = self.plant_setup_store.build_user_setup_summary(user_id=user_id)
        prompt = self._build_setup_extraction_prompt(incoming_text=incoming_text, setup_summary=setup_summary)

        try:
            raw_payload = await self.gemini_client.ask_question(api_key=api_key, prompt=prompt)
            parsed_payload = self.plant_setup_store.extract_json_payload(raw_payload)
            write_summaries = self.plant_setup_store.upsert_setup_payload(user_id=user_id, payload=parsed_payload)
            self._log_trace(
                trace_id=trace_id,
                level="info",
                agent="setup_memory_agent",
                message="Extracted static setup information from the Telegram message.",
                user_id=user_id,
                chat_id=chat_id,
                telegram_text=incoming_text,
                agent_input=prompt,
                agent_output=parsed_payload,
            )
            for write_summary in write_summaries:
                self._log_trace(
                    trace_id=trace_id,
                    level="info",
                    agent=write_summary["agent"],
                    message="Saved inferred static setup data.",
                    user_id=user_id,
                    chat_id=chat_id,
                    telegram_text=incoming_text,
                    agent_input=parsed_payload,
                    agent_output="Static setup data persisted.",
                    file_path=write_summary["file_path"],
                    persisted_data=write_summary["saved_data"],
                )
            return str(parsed_payload.get("clarification_question", "")).strip()
        except Exception as exc:  # noqa: BLE001
            self._log_trace(
                trace_id=trace_id,
                level="error",
                agent="setup_memory_agent",
                message="Failed to infer or save static setup information.",
                user_id=user_id,
                chat_id=chat_id,
                telegram_text=incoming_text,
                error=str(exc),
            )
            return ""

    async def _run_evening_outreach(self) -> None:
        """Task: Proactively send one concise setup question to users during a random evening slot.
        Input: No direct arguments; uses the current UTC time and local outreach state.
        Output: None; due users receive a short Telegram question if setup details are still missing.
        Failures: Outreach errors are logged and suppressed so the background loop keeps running.
        """

        if self.evening_outreach_store is None or self.plant_setup_store is None:
            return

        now_utc = datetime.utcnow()
        local_date = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d")
        try:
            for record in self.evening_outreach_store.due_users(now_utc=now_utc.replace(tzinfo=ZoneInfo("UTC"))):
                user_id = int(record["user_id"])
                chat_id = int(record["chat_id"])
                follow_up_question = self.plant_setup_store.next_missing_setup_question(user_id=user_id)
                if not follow_up_question:
                    self.evening_outreach_store.mark_sent(user_id=user_id, date_key=local_date)
                    continue

                trace_id = self._new_trace_id()
                await self._send_and_log(
                    trace_id=trace_id,
                    chat_id=chat_id,
                    text=follow_up_question,
                    user_id=user_id,
                    telegram_text="[proactive evening outreach]",
                    reason="Sent proactive evening setup question.",
                )
                self._log_trace(
                    trace_id=trace_id,
                    level="info",
                    agent="outreach_agent",
                    message="Sent proactive evening outreach question.",
                    user_id=user_id,
                    chat_id=chat_id,
                    telegram_text="[proactive evening outreach]",
                    agent_input={"local_window": "17:00-19:00", "question": follow_up_question},
                    agent_output="Outreach message sent.",
                    file_path=str(self.evening_outreach_store.state_path),
                    persisted_data={"user_id": user_id, "date": local_date},
                )
                self.evening_outreach_store.mark_sent(user_id=user_id, date_key=local_date)
        except Exception as exc:  # noqa: BLE001
            self._log_trace(
                trace_id=self._new_trace_id(),
                level="error",
                agent="outreach_agent",
                message="Failed during evening outreach scheduling.",
                user_id=None,
                chat_id=None,
                telegram_text="[proactive evening outreach]",
                error=str(exc),
            )

    def _build_setup_extraction_prompt(self, incoming_text: str, setup_summary: str) -> str:
        """Task: Build the structured extraction prompt used to infer static plant setup details from Telegram text.
        Input: The latest user message text and the saved setup summary for that user.
        Output: A Gemini prompt string that requests English-normalized JSON output.
        Failures: No failure is expected.
        """

        return (
            f"{SYSTEM_PERSONA_PROMPT}\n\n"
            "Extract static plant setup information from the user's latest message.\n"
            "Be objective and concise.\n"
            "The user may write in any language.\n"
            "Understand the message in that language, but translate every extracted value into concise English before returning JSON.\n"
            "Do not assume facts. If a plant name, species, cultivar, or placement is ambiguous, leave that field empty.\n"
            "If the message sounds descriptive rather than botanical, do not invent a plant variety.\n"
            "Example: 'white-green pothos' is not enough to infer the exact variety.\n"
            "Return only valid JSON with this shape:\n"
            "{\n"
            '  "clarification_question": "",\n'
            '  "rooms": [{"name":"","type":"","windows":"","size_sqft":"","has_grow_light":"","city":""}],\n'
            '  "plants": [{"name":"","species":"","room_name":"","soil_type":"","fertilizer_type":""}]\n'
            "}\n"
            "Use empty strings when a field is unknown. Include only concrete facts, not guesses.\n"
            "If there is an ambiguity, set `clarification_question` to one short English question that would resolve it. Otherwise leave it empty.\n\n"
            f"Saved setup so far:\n{setup_summary}\n\n"
            f"Latest user message:\n{incoming_text.strip()}"
        )
