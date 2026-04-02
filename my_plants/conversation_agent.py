"""Conversation handling for collecting plant profile details."""

from __future__ import annotations

import re
from typing import Any

from my_plants.utils import make_id


SOIL_KEYWORDS = {
    "cocopeat": "cocopeat",
    "potting mix": "potting mix",
    "succulent mix": "succulent mix",
    "sandy soil": "sandy soil",
    "loamy soil": "loamy soil",
    "clay soil": "clay soil",
}

KNOWN_CITIES = ("bangalore", "chennai", "delhi", "mumbai", "pune")
QUESTION_ORDER = ("watering_frequency", "soil_type", "plant_location")


class ConversationAgent:
    """Task: Collect watering frequency, soil type, and plant location details in a deterministic multi-turn flow.
    Input: Plant rows, room rows, per-user memory, and the latest user message.
    Output: Updated plant/room/memory state plus optional follow-up questions.
    Failures: Parsing may fail for ambiguous replies, resulting in clarification prompts instead of structured updates.
    """

    def begin_profile_collection(
        self,
        plant: dict[str, str],
        user_memory: dict[str, Any],
        timestamp: str,
    ) -> dict[str, Any]:
        """Task: Start a new profile-collection flow for a plant that lacks scheduler details. Return state."""
        question_key = self._next_missing_field(plant=plant, user_memory=user_memory)
        if not question_key:
            return {"conversation_state": None, "response": f"I added {plant['name']}."}

        state = {
            "plant_id": plant["id"],
            "pending_question": question_key,
            "question_context": question_key,
            "timestamp": timestamp,
        }
        return {
            "conversation_state": state,
            "response": f"I added {plant['name']}. {self._question_text(question_key, plant['name'])}",
        }

    def get_next_question_state(
        self,
        plant: dict[str, str],
        user_memory: dict[str, Any],
        timestamp: str,
    ) -> dict[str, Any] | None:
        """Task: Get the conversation state and text for the next missing profile question."""
        question_key = self._next_missing_field(plant=plant, user_memory=user_memory)
        if not question_key:
            return None

        state = {
            "plant_id": plant["id"],
            "pending_question": question_key,
            "question_context": question_key,
            "timestamp": timestamp,
        }
        return {
            "conversation_state": state,
            "response": f"Got it for {plant['name']}. {self._question_text(question_key, plant['name'])}",
        }

    def _next_missing_field(self, plant: dict[str, str], user_memory: dict[str, Any]) -> str | None:
        """Task: Determine which plant-profile field should be collected next.
        Input: The plant row and per-user memory state.
        Output: The next question key or None when the profile is complete.
        Failures: No failure is expected.
        """

        preferences = user_memory.get("plant_preferences", {}).get(plant["id"], {})
        for question_key in QUESTION_ORDER:
            if question_key == "watering_frequency" and not preferences.get("user_defined_watering_interval_days"):
                return question_key
            if question_key == "soil_type" and not plant.get("soil_type"):
                return question_key
            if question_key == "plant_location" and not preferences.get("location_confirmed"):
                return question_key
        return None

    def _question_text(self, question_key: str, plant_name: str) -> str:
        """Task: Return a friendly next-question prompt for the requested profile field.
        Input: The question key and plant name.
        Output: A conversational prompt string.
        Failures: No failure is expected.
        """

        questions = {
            "watering_frequency": f"How often do you usually water {plant_name}? Please answer in days, like 'every 5 days'.",
            "soil_type": f"What soil type is {plant_name} in? For example: cocopeat, potting mix, succulent mix, sandy soil, loamy soil, or clay soil.",
            "plant_location": f"Which room is {plant_name} in? (For example: Bedroom, Living Room, etc.)",
        }
        return questions[question_key]

    def _clarification_text(self, question_key: str, plant_name: str) -> str:
        """Task: Return a deterministic clarification prompt when an answer could not be parsed.
        Input: The question key and plant name.
        Output: A clarification message string.
        Failures: No failure is expected.
        """

        clarifications = {
            "watering_frequency": f"I still need the watering frequency for {plant_name} as a number of days, like 'every 7 days'.",
            "soil_type": f"I still need the soil type for {plant_name}. Try one of: cocopeat, potting mix, succulent mix, sandy soil, loamy soil, or clay soil.",
            "plant_location": f"I didn't get that. Which room is {plant_name} in? (For example: Bedroom, Living Room, or Balcony)",
        }
        return clarifications[question_key]

    def _parse_watering_frequency(self, message: str) -> dict[str, int] | None:
        """Task: Parse a user-defined watering interval in days from message text.
        Input: A free-form user message.
        Output: A dictionary containing the parsed day count, or None when parsing fails.
        Failures: No failure is expected.
        """

        lowered = message.lower()
        if "every day" in lowered or "daily" in lowered:
            return {"days": 1}
        if "once a week" in lowered or "weekly" in lowered:
            return {"days": 7}
        match = re.search(r"(\d+)", lowered)
        if not match:
            return None
        return {"days": max(int(match.group(1)), 1)}

    def _parse_soil_type(self, message: str) -> dict[str, str] | None:
        """Task: Parse a known soil type from message text.
        Input: A free-form user message.
        Output: A dictionary containing the canonical soil type, or None when parsing fails.
        Failures: No failure is expected.
        """

        lowered = message.lower()
        for keyword, canonical in SOIL_KEYWORDS.items():
            if keyword in lowered:
                return {"soil_type": canonical}
        return None

    def _parse_location(self, message: str) -> dict[str, str] | None:
        """Task: Parse room name and type from a location answer.
        Input: A free-form user message.
        Output: A location payload dictionary, or None when parsing fails.
        Failures: No failure is expected.
        """

        clean_message = message.strip()
        lowered = clean_message.lower()
        if not lowered:
            return None

        room_type = "indoor"
        if "balcony" in lowered:
            room_type = "balcony"
        elif "outdoor" in lowered:
            room_type = "outdoor"

        return {
            "name": clean_message.title(),
            "type": room_type,
            "windows": "",
            "city": "",
        }

    def _upsert_room(
        self,
        user_id: str,
        rooms: list[dict[str, str]],
        location_payload: dict[str, str],
    ) -> dict[str, str]:
        """Task: Create or update the room row associated with a parsed location answer.
        Input: The user id, existing room rows, and parsed location fields.
        Output: The created or updated room row.
        Failures: No failure is expected.
        """

        existing_room = next(
            (
                room
                for room in rooms
                if room["user_id"] == user_id and room["name"].lower() == location_payload["name"].lower()
            ),
            None,
        )
        if existing_room is None:
            existing_room = {
                "id": make_id("room"),
                "user_id": user_id,
                "name": location_payload["name"],
                "type": location_payload["type"],
                "windows": location_payload.get("windows", ""),
                "size_sqft": "",
                "has_grow_light": "false",
                "city": location_payload.get("city", ""),
            }
            rooms.append(existing_room)
            return existing_room

        existing_room["type"] = location_payload["type"] or existing_room["type"]
        existing_room["windows"] = location_payload.get("windows", "") or existing_room.get("windows", "")
        existing_room["city"] = location_payload.get("city", "") or existing_room["city"]
        return existing_room
