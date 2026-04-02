"""Tests for the Gemini-backed My Plants phrasing layer."""

from __future__ import annotations

from my_plants.reminder_agent import ReminderAgent
from my_plants.response_generator import ResponseGenerator


class FakeGeminiInferenceClient:
    """Task: Provide a fake Gemini client for prompt-layer unit tests.
    Input: A canned response string that should be returned to the caller.
    Output: A fake client that records prompts and behaves like the real interface.
    Failures: No failure is expected.
    """

    def __init__(self, response_text: str) -> None:
        """Task: Initialize the fake Gemini client with a canned response.
        Input: The response text that should be returned from generate_text.
        Output: A ready-to-use fake Gemini inference client.
        Failures: No failure is expected.
        """

        self.response_text = response_text
        self.prompts: list[str] = []

    def is_configured(self) -> bool:
        """Task: Report that the fake Gemini client is configured.
        Input: No direct arguments.
        Output: Always True.
        Failures: No failure is expected.
        """

        return True

    def generate_text(self, prompt: str) -> str:
        """Task: Record the prompt and return the canned Gemini response.
        Input: The prompt text sent by the agent under test.
        Output: The canned response string.
        Failures: No failure is expected.
        """

        self.prompts.append(prompt)
        return self.response_text


def test_response_generator_uses_gemini_when_configured() -> None:
    """Task: Verify that the plant response generator routes through Gemini when configured.
    Input: No filesystem input; uses an in-memory fake Gemini client.
    Output: None; assertions verify the generated reply and prompt contents.
    Failures: Test fails if Gemini is not used or the prompt omits key context.
    """

    fake_client = FakeGeminiInferenceClient("Pothos feels pretty steady today 🌿")
    generator = ResponseGenerator(gemini_client=fake_client)
    result = generator.generate(
        context={
            "plant": {"id": "plant_1", "name": "Pothos", "species": "pothos", "soil_type": "potting mix", "fertilizer_type": ""},
            "room": {"type": "indoor", "window_direction": "north", "city": "Mumbai"},
            "plant_requirements": {"watering_interval_days": 5, "notes": ["Let the soil dry slightly between waterings."]},
        },
        analysis={
            "avg_watering_interval_days_last5": 4.0,
            "frequent_watering": False,
        },
        decisions={
            "recommendations": ["Indoor placement usually means watering should be less frequent."],
            "warnings": [],
        },
        latest_activity="Last time, you watered it on 2026-04-02T10:00:00.",
        watering_schedule={
            "days_since_last_watered": 3,
            "watering_interval_days": 4.0,
            "reminder_due": False,
            "last_watering_timestamp": "2026-04-02T10:00:00",
        },
    )

    assert result == "Pothos feels pretty steady today 🌿"
    assert fake_client.prompts
    assert 'You are "My Plants"' in fake_client.prompts[0]
    assert "Plant name: Pothos" in fake_client.prompts[0]
    assert "Computed watering interval days: 4.0" in fake_client.prompts[0]


def test_reminder_agent_uses_gemini_when_configured() -> None:
    """Task: Verify that the reminder agent routes grouped reminders through Gemini when configured.
    Input: No filesystem input; uses an in-memory fake Gemini client.
    Output: None; assertions verify the reminder text and prompt contents.
    Failures: Test fails if Gemini is not used or due-plant context is missing from the prompt.
    """

    fake_client = FakeGeminiInferenceClient("Hey… Pothos and Philodendron might be ready for some water today 🌿")
    agent = ReminderAgent(gemini_client=fake_client)
    result = agent.generate(
        due_plants=[
            {"plant": {"name": "Pothos"}, "schedule": {"days_since_last_watered": 5, "watering_interval_days": 4.0}},
            {"plant": {"name": "Philodendron"}, "schedule": {"days_since_last_watered": 5, "watering_interval_days": 4.0}},
        ],
        now_timestamp="2026-04-05T09:00:00",
    )

    assert result == "Hey… Pothos and Philodendron might be ready for some water today 🌿"
    assert fake_client.prompts
    assert "Plants due for watering:" in fake_client.prompts[0]
    assert "- Pothos: days since last watered=5, interval=4.0" in fake_client.prompts[0]
    assert "- Philodendron: days since last watered=5, interval=4.0" in fake_client.prompts[0]
