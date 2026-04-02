"""Tests for Telegram bot orchestration behavior."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import app.main
from app.services.bot import BotService
from app.services.session import SessionManager
from app.services.storage import UserKeyStore
from app.services.trace_logger import TraceLogger


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
    assert gemini_client.prompts
    assert 'You are "Anirban"' in gemini_client.prompts[0]
    assert "Be concise and objective. Avoid being verbose." in gemini_client.prompts[0]
    assert "reply in the same language as the user's message" in gemini_client.prompts[0].lower()
    assert "User message:\nWhat is the weather?" in gemini_client.prompts[0]


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
    await bot_service._watch_question_job(
        trace_id="trace_test",
        user_id=98765,
        chat_id=12345,
        telegram_text="bold prompt",
        question_job=question_job,
    )

    assert telegram_client.sent_messages == [(12345, "Bold answer")]


@pytest.mark.asyncio
async def test_handle_message_writes_dashboard_trace(tmp_path: Path) -> None:
    """Task: Verify that one Telegram request produces grouped dashboard trace events.
    Input: A temporary filesystem path provided by pytest for CSV and trace storage.
    Output: None; assertions confirm agent inputs, outputs, and final reply are logged.
    Failures: Test fails if the request flow is not captured in the trace log.
    """

    key_store = UserKeyStore(tmp_path / "keys.csv")
    key_store.ensure_store_exists()
    session_manager = SessionManager(key_store=key_store, timeout_seconds=180)
    await session_manager.update_api_key(user_id=98765, gemini_api_key="valid-key")

    trace_logger = TraceLogger(tmp_path / "traces.jsonl")
    telegram_client = FakeTelegramClient()
    gemini_client = FakeGeminiClient(answer="plain answer")
    bot_service = BotService(
        telegram_client=telegram_client,
        gemini_client=gemini_client,
        session_manager=session_manager,
        key_store=key_store,
        poll_interval_seconds=0,
        trace_logger=trace_logger,
    )

    await bot_service.handle_message(build_message("What is the weather?"))
    await bot_service.monitor_tasks[98765]

    traces = trace_logger.read_recent_traces(limit=5)
    assert len(traces) == 1
    trace = traces[0]
    agents = [event["agent"] for event in trace["events"]]
    assert "telegram_input_agent" in agents
    assert "session_agent" in agents
    assert "gemini_agent" in agents
    assert "telegram_output_agent" in agents
    assert trace["telegram_text"] == "What is the weather?"
    assert trace["final_output"] == "plain answer"


def test_dashboard_route_renders_logged_trace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Task: Verify that the `/dashboard` page renders recent trace data without authorization.
    Input: A temporary filesystem path provided by pytest and a monkeypatched trace logger.
    Output: None; assertions confirm the HTML includes logged trace content.
    Failures: Test fails if the dashboard route cannot render the trace log page.
    """

    trace_logger = TraceLogger(tmp_path / "dashboard_traces.jsonl")
    trace_logger.log_event(
        trace_id="trace_1",
        level="info",
        agent="telegram_input_agent",
        message="Received Telegram message.",
        user_id=1,
        chat_id=2,
        telegram_text="Hello plant",
        agent_input={"text": "Hello plant"},
        agent_output="Webhook payload accepted.",
    )
    trace_logger.log_event(
        trace_id="trace_1",
        level="info",
        agent="telegram_output_agent",
        message="Delivered final Gemini answer to Telegram.",
        user_id=1,
        chat_id=2,
        telegram_text="Hello plant",
        agent_input={"chat_id": 2},
        agent_output="Hello back 🌿",
        file_path="data/user_gemini_keys.csv",
        persisted_data={"user_id": 1, "gemini_api_key": "abcd...wxyz"},
    )

    monkeypatch.setattr(app.main, "trace_logger", trace_logger)
    client = TestClient(app.main.app)
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "myPlant Dashboard" in response.text
    assert "Hello plant" in response.text
    assert "telegram_input_agent" in response.text
    assert "Hello back 🌿" in response.text
    assert "data/user_gemini_keys.csv" in response.text
    assert "abcd...wxyz" in response.text


def test_setup_extraction_prompt_requires_english_normalization() -> None:
    """Task: Verify that setup extraction prompts request English-normalized saved data even for non-English input.
    Input: No filesystem input; constructs the bot service with lightweight fakes.
    Output: None; assertions confirm the prompt instructions.
    Failures: Test fails if the extraction prompt stops requiring English-normalized saved values.
    """

    bot_service = BotService(
        telegram_client=FakeTelegramClient(),
        gemini_client=FakeGeminiClient(),
        session_manager=SessionManager(key_store=UserKeyStore(Path("unused.csv")), timeout_seconds=180),
        key_store=UserKeyStore(Path("unused.csv")),
        poll_interval_seconds=0,
    )
    prompt = bot_service._build_setup_extraction_prompt(
        incoming_text="मेरे पौधे रसोई में हैं",
        setup_summary="No saved plant setup information yet.",
        history_text="No prior context.",
    )

    assert "The user may write in any language." in prompt
    assert "translate every extracted value into concise English before returning JSON" in prompt
    assert "Do not assume facts arbitrarily" in prompt
    assert "white-green pothos" in prompt
    assert '"clarification_question": ""' in prompt
    assert "Latest user message:\nमेरे पौधे रसोई में हैं" in prompt


def test_persona_prompt_requires_clarification_instead_of_guessing() -> None:
    """Task: Verify that the main Gemini answer prompt tells the bot to clarify ambiguous plant details instead of guessing.
    Input: No filesystem input; constructs the bot service with lightweight fakes.
    Output: None; assertions confirm the ambiguity-handling instructions in the prompt.
    Failures: Test fails if the user-facing answer prompt stops discouraging guesses about species or placement.
    """

    bot_service = BotService(
        telegram_client=FakeTelegramClient(),
        gemini_client=FakeGeminiClient(),
        session_manager=SessionManager(key_store=UserKeyStore(Path("unused.csv")), timeout_seconds=180),
        key_store=UserKeyStore(Path("unused.csv")),
        poll_interval_seconds=0,
    )

    prompt = bot_service._build_persona_prompt(
        user_text="My white-green pothos is by the window.",
        setup_summary="No saved plant setup information yet.",
        follow_up_question="Which window direction is it near?",
    )

    assert "German man in his mid-40s with a PhD in indoor plants" in prompt
    assert "Do not pretend to know the exact species, variety, cultivar, room placement, or light setup" in prompt
    assert "If something important is ambiguous, ask one short clarifying question instead of guessing." in prompt
    assert "Which window direction is it near?" in prompt
