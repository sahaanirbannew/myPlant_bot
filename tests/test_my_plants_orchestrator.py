"""Tests for the deterministic My Plants backend."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from my_plants.orchestrator import build_default_orchestrator


def test_bought_message_creates_new_plant_and_files(tmp_path: Path) -> None:
    """Task: Verify that a purchase-style message creates a plant row and starts profile collection.
    Input: A pytest temporary directory used as the backend base path.
    Output: None; assertions verify file-backed behavior.
    Failures: Test fails if the plant row is not created or the follow-up question does not start.
    """

    orchestrator = build_default_orchestrator(base_dir=tmp_path)
    response = orchestrator.handle(
        user_id="u1",
        message="I bought a snake plant for the balcony.",
        now=datetime(2026, 4, 2, 12, 0, 0),
    )

    plants_path = tmp_path / "data" / "users" / "u1" / "plants.csv"
    plants_csv = plants_path.read_text(encoding="utf-8")
    assert "Snake" in plants_csv
    assert "how often do you usually water snake plant" in response.lower()


def test_profile_conversation_updates_override_soil_and_location(tmp_path: Path) -> None:
    """Task: Verify that the conversation agent stores watering frequency, soil type, and location data.
    Input: A pytest temporary directory used as the backend base path.
    Output: None; assertions verify memory, plant, and room persistence.
    Failures: Test fails if the conversation state or persisted fields are not updated.
    """

    orchestrator = build_default_orchestrator(base_dir=tmp_path)
    first_response = orchestrator.handle(
        user_id="u1",
        message="I bought a pothos.",
        now=datetime(2026, 4, 2, 12, 0, 0),
    )
    second_response = orchestrator.handle(
        user_id="u1",
        message="every 4 days",
        now=datetime(2026, 4, 2, 12, 1, 0),
    )
    third_response = orchestrator.handle(
        user_id="u1",
        message="cocopeat",
        now=datetime(2026, 4, 2, 12, 2, 0),
    )
    final_response = orchestrator.handle(
        user_id="u1",
        message="indoors by the north window in Mumbai",
        now=datetime(2026, 4, 2, 12, 3, 0),
    )

    memory_json = (tmp_path / "data" / "users" / "u1" / "memory.json").read_text(encoding="utf-8")
    plants_csv = (tmp_path / "data" / "users" / "u1" / "plants.csv").read_text(encoding="utf-8")
    rooms_csv = (tmp_path / "data" / "users" / "u1" / "rooms.csv").read_text(encoding="utf-8")

    assert "how often do you usually water pothos" in first_response.lower()
    assert "what soil type is pothos" in second_response.lower()
    assert "which room is pothos in" in third_response.lower()
    assert "saved the watering profile for pothos" in final_response.lower()
    assert '"user_defined_watering_interval_days": 4' in memory_json
    assert "cocopeat" in plants_csv
    assert "indoor room" in rooms_csv.lower()
    assert "north" in rooms_csv.lower()


def test_last_used_plant_is_reused_for_follow_up_event(tmp_path: Path) -> None:
    """Task: Verify that follow-up messages fall back to the last used plant when no name is present.
    Input: A pytest temporary directory used as the backend base path.
    Output: None; assertions verify event persistence and watering guidance.
    Failures: Test fails if the watering event is not attached to the previously used plant.
    """

    orchestrator = build_default_orchestrator(base_dir=tmp_path)
    orchestrator.handle(
        user_id="u1",
        message="I bought a pothos.",
        now=datetime(2026, 4, 2, 12, 0, 0),
    )
    orchestrator.handle(
        user_id="u1",
        message="every 4 days",
        now=datetime(2026, 4, 2, 12, 1, 0),
    )
    orchestrator.handle(
        user_id="u1",
        message="potting mix",
        now=datetime(2026, 4, 2, 12, 2, 0),
    )
    orchestrator.handle(
        user_id="u1",
        message="on the balcony in Bangalore",
        now=datetime(2026, 4, 2, 12, 3, 0),
    )
    response = orchestrator.handle(
        user_id="u1",
        message="I watered it today.",
        now=datetime(2026, 4, 3, 12, 0, 0),
    )

    events_csv = (tmp_path / "data" / "users" / "u1" / "events.csv").read_text(encoding="utf-8")
    assert "watering" in events_csv
    assert "pothos" in response.lower()
    assert "last time, you watered it" in response.lower()
    assert "around every 4.0 day(s)" in response.lower()
    assert "guidance:" not in response.lower()
    assert "warning:" not in response.lower()


def test_frequent_watering_warning_is_generated(tmp_path: Path) -> None:
    """Task: Verify that frequent watering produces an overwatering warning.
    Input: A pytest temporary directory used as the backend base path.
    Output: None; assertions verify deterministic warning logic.
    Failures: Test fails if the frequent-watering warning is not included in the response.
    """

    orchestrator = build_default_orchestrator(base_dir=tmp_path)
    orchestrator.handle(
        user_id="u1",
        message="I bought a peace lily indoors by the north window.",
        now=datetime(2026, 4, 2, 9, 0, 0),
    )
    orchestrator.handle(
        user_id="u1",
        message="every 3 days",
        now=datetime(2026, 4, 2, 9, 1, 0),
    )
    orchestrator.handle(
        user_id="u1",
        message="potting mix",
        now=datetime(2026, 4, 2, 9, 2, 0),
    )
    orchestrator.handle(
        user_id="u1",
        message="indoor room",
        now=datetime(2026, 4, 2, 9, 3, 0),
    )
    orchestrator.handle(
        user_id="u1",
        message="it is near the north window",
        now=datetime(2026, 4, 2, 9, 4, 0),
    )
    orchestrator.handle(
        user_id="u1",
        message="I watered Peace Lily.",
        now=datetime(2026, 4, 2, 10, 0, 0),
    )
    response = orchestrator.handle(
        user_id="u1",
        message="I watered Peace Lily again.",
        now=datetime(2026, 4, 3, 9, 0, 0),
    )

    assert "possible overwatering" in response.lower()
    assert "north-facing" in response.lower()
    assert "indoors" in response.lower()
    assert "one thing i’m noticing" in response.lower() or "one thing i'm noticing" in response.lower()


def test_reminder_agent_groups_due_plants(tmp_path: Path) -> None:
    """Task: Verify that the reminder agent groups due plants into one friendly response.
    Input: A pytest temporary directory used as the backend base path.
    Output: None; assertions verify grouped reminder text.
    Failures: Test fails if multiple due plants are not included in the reminder message.
    """

    orchestrator = build_default_orchestrator(base_dir=tmp_path)
    for plant_name in ("Pothos", "Philodendron"):
        orchestrator.handle(
            user_id="u1",
            message=f"I bought a {plant_name}.",
            now=datetime(2026, 4, 1, 8, 0, 0),
        )
        orchestrator.handle(
            user_id="u1",
            message="every 2 days",
            now=datetime(2026, 4, 1, 8, 1, 0),
        )
        orchestrator.handle(
            user_id="u1",
            message="potting mix",
            now=datetime(2026, 4, 1, 8, 2, 0),
        )
        orchestrator.handle(
            user_id="u1",
            message="indoors in Bangalore",
            now=datetime(2026, 4, 1, 8, 3, 0),
        )
        orchestrator.handle(
            user_id="u1",
            message=f"I watered {plant_name}.",
            now=datetime(2026, 4, 1, 9, 0, 0),
        )

    reminder = orchestrator.scan_due_plants(user_id="u1", now=datetime(2026, 4, 5, 9, 0, 0))

    assert "pothos" in reminder.lower()
    assert "philodendron" in reminder.lower()
    assert "might be ready for some water" in reminder.lower() or "due for a drink" in reminder.lower() or "ready for watering" in reminder.lower()


def test_response_generator_uses_warm_persona_voice(tmp_path: Path) -> None:
    """Task: Verify that deterministic care replies follow the warmer My Plants persona style.
    Input: A pytest temporary directory used as the backend base path.
    Output: None; assertions verify the friendly tone and gentle reminder phrasing.
    Failures: Test fails if the response falls back to robotic status-report wording.
    """

    orchestrator = build_default_orchestrator(base_dir=tmp_path)
    orchestrator.handle(
        user_id="u1",
        message="I bought a pothos.",
        now=datetime(2026, 4, 1, 8, 0, 0),
    )
    orchestrator.handle(
        user_id="u1",
        message="every 2 days",
        now=datetime(2026, 4, 1, 8, 1, 0),
    )
    orchestrator.handle(
        user_id="u1",
        message="potting mix",
        now=datetime(2026, 4, 1, 8, 2, 0),
    )
    orchestrator.handle(
        user_id="u1",
        message="indoor room",
        now=datetime(2026, 4, 1, 8, 3, 0),
    )
    orchestrator.handle(
        user_id="u1",
        message="north window",
        now=datetime(2026, 4, 1, 8, 4, 0),
    )
    orchestrator.handle(
        user_id="u1",
        message="I watered pothos.",
        now=datetime(2026, 4, 1, 9, 0, 0),
    )
    response = orchestrator.handle(
        user_id="u1",
        message="How is pothos doing?",
        now=datetime(2026, 4, 4, 8, 0, 0),
    )

    assert "pothos" in response.lower()
    assert "might be ready for some water today" in response.lower()
    assert "north-facing light" in response.lower()
