"""Plant resolution logic for incoming messages."""

from __future__ import annotations

import re
from typing import Any

from my_plants.file_manager import PLANT_HEADERS
from my_plants.utils import iso_now, make_id


CREATE_CUES = ("bought", "got a")
STOP_WORDS = {
    "a",
    "an",
    "the",
    "for",
    "in",
    "on",
    "at",
    "because",
    "today",
    "yesterday",
    "this",
    "my",
    "balcony",
    "indoors",
    "indoor",
    "north",
    "south",
    "east",
    "west",
    "window",
    "room",
}


class PlantResolver:
    """Task: Resolve which plant a message refers to, or create a new plant record when needed.
    Input: Existing plant rows, user memory, and the incoming message text.
    Output: A resolution dictionary containing the target plant and optional creation data.
    Failures: May return no plant when the message is ambiguous and no last-used plant exists.
    """

    def resolve(
        self,
        user_id: str,
        message: str,
        plants: list[dict[str, str]],
        user_memory: dict[str, Any],
        timestamp: str,
    ) -> dict[str, Any]:
        """Task: Apply deterministic plant resolution rules to a user message.
        Input: The user id, message text, current plant rows, per-user memory, and event timestamp.
        Output: A dictionary describing the resolved plant row, whether one was created, and whether clarification is needed.
        Failures: No failure is expected; ambiguous input returns a `needs_clarification` outcome.
        """

        user_plants = [plant for plant in plants if plant["user_id"] == user_id]
        lowered_message = message.lower()

        for plant in user_plants:
            if plant["name"] and plant["name"].lower() in lowered_message:
                return {
                    "plant": plant,
                    "created": False,
                    "needs_clarification": False,
                }

        if any(cue in lowered_message for cue in CREATE_CUES):
            plant_name = self._extract_new_plant_name(message)
            plant_row = {
                "id": make_id("plant"),
                "user_id": user_id,
                "name": plant_name,
                "species": plant_name,
                "room_id": "",
                "position_in_room": "",
                "soil_type": "",
                "fertilizer_type": "",
                "created_at": timestamp,
            }
            return {
                "plant": plant_row,
                "created": True,
                "needs_clarification": False,
            }

        last_used_plant_id = str(user_memory.get("last_used_plant_id", "")).strip()
        if last_used_plant_id:
            for plant in user_plants:
                if plant["id"] == last_used_plant_id:
                    return {
                        "plant": plant,
                        "created": False,
                        "needs_clarification": False,
                    }

        return {
            "plant": None,
            "created": False,
            "needs_clarification": True,
        }

    def _extract_new_plant_name(self, message: str) -> str:
        """Task: Derive a deterministic plant name from a purchase-style message.
        Input: The raw user message text.
        Output: A normalized plant name string.
        Failures: Falls back to `New Plant` when no useful name tokens are found.
        """

        lowered_message = message.lower()
        matched_cue = next((cue for cue in CREATE_CUES if cue in lowered_message), "")
        candidate = lowered_message.split(matched_cue, 1)[1] if matched_cue else lowered_message
        cleaned = re.sub(r"[^a-z0-9\s]", " ", candidate)
        tokens = cleaned.split()

        name_tokens: list[str] = []
        for token in tokens:
            if token in STOP_WORDS and name_tokens:
                break
            if token in STOP_WORDS:
                continue
            name_tokens.append(token)

        name = " ".join(name_tokens[:3]).strip()
        if not name:
            return "New Plant"
        return " ".join(word.capitalize() for word in name.split())
