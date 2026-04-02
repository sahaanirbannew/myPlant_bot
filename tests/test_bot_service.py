"""Tests for Telegram bot orchestration behavior."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.bot import BotService
from app.services.session import SessionManager
from app.services.storage import UserKeyStore


class FakeTelegramClient:
    """Task: Capture outbound Telegram messages for assertions in tests.
    Input: Calls to send_message from the bot service during a test run.
    Output: An in-memory list of sent chat ids and message texts.
    Failures: No failure is expected unless tests inspect attributes that were never populated.
    """

    def __init__(self) -> None:
        """Task: Initialize the fake Telegram client with an empty send log.
        Input: No arguments.
        Output: A ready-to-use fake client instance.
        Failures: No failure is expected.
        """

        self.sent_messages: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        """Task: Record a message that the bot attempted to send to Telegram.
        Input: The chat id and text that would have been sent to Telegram.
        Output: None; the send operation is captured in memory.
        Failures: No failure is expected.
        """

        self.sent_messages.append((chat_id, text))


class FakeGeminiClient:
    """Task: Provide deterministic Gemini responses for unit tests.
    Input: Predefined answer text returned by ask_question invocations.
    Output: Async Gemini-like behavior without real network access.
    Failures: No failure is expected unless the test overrides behavior incorrectly.
    """

    def __init__(self, answer: str = "ok") -> None:
        """Task: Initialize the fake Gemini client with a canned answer.
        Input: The answer text to return for ask_question calls.
        Output: A ready-to-use fake Gemini client instance.
        Failures: No failure is expected.
        """

        self.answer = answer
        self.prompts: list[str] = []

    async def ask_question(self, api_key: str, prompt: str) -> str:
        """Task: Return a canned Gemini answer while recording the prompt for assertions.
        Input: An API key and the user prompt text.
        Output: The configured answer text.
        Failures: No failure is expected.
        """

        self.prompts.append(prompt)
        return self.answer


def build_message(text: str) -> SimpleNamespace:
    """Task: Create a lightweight Telegram-like message object for tests.
    Input: The text content to include in the fake Telegram message.
    Output: A SimpleNamespace matching the fields BotService reads.
    Failures: No failure is expected.
    """

    return SimpleNamespace(
        text=text,
        chat=SimpleNamespace(id=12345),
        from_user=SimpleNamespace(id=98765),
    )


@pytest.mark.asyncio
async def test_handle_message_skips_processing_notice(tmp_path: Path) -> None:
    """Task: Verify the bot no longer sends an interim background-processing message.
    Input: A temporary filesystem path provided by pytest for CSV storage.
    Output: None; assertions confirm the observed bot behavior.
    Failures: Test fails if the bot emits an interim processing notice.
    """

    key_store = UserKeyStore(tmp_path / "keys.csv")
    key_store.ensure_store_exists()
    session_manager = SessionManager(key_store=key_store, timeout_seconds=180)
    await session_manager.update_api_key(user_id=98765, gemini_api_key="valid-key")

    telegram_client = FakeTelegramClient()
    gemini_client = FakeGeminiClient(answer="plain answer")
    bot_service = BotService(
        telegram_client=telegram_client,
        gemini_client=gemini_client,
        session_manager=session_manager,
        key_store=key_store,
        poll_interval_seconds=0,
    )

    await bot_service.handle_message(build_message("What is the weather?"))
    await bot_service.monitor_tasks[98765]

    assert telegram_client.sent_messages == [(12345, "plain answer")]


@pytest.mark.asyncio
async def test_watch_question_job_removes_bold_markers(tmp_path: Path) -> None:
    """Task: Verify the bot strips double-asterisk bold markers before replying in Telegram.
    Input: A temporary filesystem path provided by pytest for CSV storage.
    Output: None; assertions confirm the sanitized reply text.
    Failures: Test fails if bold markers remain in the Telegram-facing response.
    """

    key_store = UserKeyStore(tmp_path / "keys.csv")
    key_store.ensure_store_exists()
    session_manager = SessionManager(key_store=key_store, timeout_seconds=180)
    telegram_client = FakeTelegramClient()
    gemini_client = FakeGeminiClient(answer="ignored")
    bot_service = BotService(
        telegram_client=telegram_client,
        gemini_client=gemini_client,
        session_manager=session_manager,
        key_store=key_store,
        poll_interval_seconds=0,
    )

    question_job: asyncio.Task[str] = asyncio.create_task(asyncio.sleep(0, result="**Bold** answer"))
    await bot_service._watch_question_job(user_id=98765, chat_id=12345, question_job=question_job)

    assert telegram_client.sent_messages == [(12345, "Bold answer")]
