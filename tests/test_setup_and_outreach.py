"""Tests for plant setup persistence and evening outreach scheduling."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.services.evening_outreach import EveningOutreachStore
from app.services.plant_setup_store import PlantSetupStore


def test_plant_setup_store_persists_rooms_and_plants(tmp_path: Path) -> None:
    """Task: Verify that inferred static setup facts are saved into the existing room and plant CSV files.
    Input: A pytest temporary directory used as the My Plants package root.
    Output: None; assertions verify file-backed persistence and follow-up question logic.
    Failures: Test fails if room and plant data are not written with the expected fields.
    """

    store = PlantSetupStore(base_dir=tmp_path)
    write_summaries = store.upsert_setup_payload(
        user_id=123,
        payload={
            "rooms": [
                {
                    "name": "Living Room",
                    "type": "indoor",
                    "window_direction": "east",
                    "size_sqft": "140",
                    "has_grow_light": "true",
                    "city": "Mumbai",
                }
            ],
            "plants": [
                {
                    "name": "Pothos",
                    "species": "Epipremnum aureum",
                    "room_name": "Living Room",
                    "position_in_room": "near the bookshelf",
                    "soil_type": "potting mix",
                    "fertilizer_type": "",
                }
            ],
        },
        timestamp="2026-04-02T18:00:00",
    )

    plants_csv = (tmp_path / "data" / "plants.csv").read_text(encoding="utf-8")
    rooms_csv = (tmp_path / "data" / "rooms.csv").read_text(encoding="utf-8")

    assert "Living Room" in rooms_csv
    assert "140" in rooms_csv
    assert "true" in rooms_csv
    assert "Epipremnum aureum" in plants_csv
    assert "near the bookshelf" in plants_csv
    assert any(summary["file_path"].endswith("rooms.csv") for summary in write_summaries)
    assert any(summary["file_path"].endswith("plants.csv") for summary in write_summaries)
    assert store.next_missing_setup_question(user_id=123) == "What fertilizer do you use for your Pothos?"


def test_evening_outreach_store_returns_due_users_in_evening_window(tmp_path: Path) -> None:
    """Task: Verify that proactive evening outreach is scheduled once per user during the 5 PM to 7 PM window.
    Input: A pytest temporary directory used for the outreach registry and state JSON files.
    Output: None; assertions verify due-user selection and daily send tracking.
    Failures: Test fails if due users are not selected or repeat sends are not suppressed.
    """

    store = EveningOutreachStore(
        registry_path=tmp_path / "telegram_user_registry.json",
        state_path=tmp_path / "evening_outreach_state.json",
    )
    store.register_user(user_id=123, chat_id=456)

    due_users = store.due_users(now_utc=datetime(2026, 4, 2, 13, 29, tzinfo=timezone.utc))
    assert due_users
    assert due_users[0]["chat_id"] == 456

    store.mark_sent(user_id=123, date_key="2026-04-02")
    assert store.due_users(now_utc=datetime(2026, 4, 2, 13, 29, tzinfo=timezone.utc)) == []
