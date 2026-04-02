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
        """Task: Start a new profile-collection flow for a plant that lacks scheduler details.
        Input: The target plant row, current user memory, and current timestamp.
        Output: Updated memory state and the first follow-up question.
        Failures: No failure is expected.
        """

        pending_question = {
            "plant_id": plant["id"],
            "question_key": self._next_missing_field(plant=plant, user_memory=user_memory),
            "started_at": timestamp,
        }
        updated_memory = dict(user_memory)
        updated_memory["pending_question"] = pending_question
        return {
            "memory": updated_memory,
            "response": f"I added {plant['name']}. {self._question_text(pending_question['question_key'], plant['name'])}",
        }

    def handle_pending_question(
        self,
        user_id: str,
        plant: dict[str, str],
        rooms: list[dict[str, str]],
        user_memory: dict[str, Any],
        message: str,
        timestamp: str,
    ) -> dict[str, Any]:
        """Task: Process an answer to the current profile question and ask the next one if needed.
        Input: User id, plant row, rooms, user memory, raw answer text, and current timestamp.
        Output: A dictionary describing whether the pending question was handled plus updated state and reply text.
        Failures: Ambiguous answers produce a clarification response without applying updates.
        """

        pending_question = user_memory.get("pending_question")
        if not pending_question or pending_question.get("plant_id") != plant["id"]:
            return {"handled": False}

        question_key = pending_question["question_key"]
        parser = {
            "watering_frequency": self._parse_watering_frequency,
            "soil_type": self._parse_soil_type,
            "plant_location": self._parse_location,
        }[question_key]
        parsed_value = parser(message)
        if not parsed_value:
            return {
                "handled": True,
                "memory": user_memory,
                "plant": plant,
                "rooms": rooms,
                "response": self._clarification_text(question_key, plant["name"]),
            }

        updated_memory = dict(user_memory)
        updated_plant = dict(plant)
        updated_rooms = list(rooms)
        preferences = dict(updated_memory.get("plant_preferences", {}))
        plant_preferences = dict(preferences.get(plant["id"], {}))

        if question_key == "watering_frequency":
            plant_preferences["user_defined_watering_interval_days"] = parsed_value["days"]

        if question_key == "soil_type":
            updated_plant["soil_type"] = parsed_value["soil_type"]

        if question_key == "plant_location":
            room = self._upsert_room(
                user_id=user_id,
                rooms=updated_rooms,
                location_payload=parsed_value,
            )
            updated_plant["room_id"] = room["id"]
            plant_preferences["location_confirmed"] = True

        preferences[plant["id"]] = plant_preferences
        updated_memory["plant_preferences"] = preferences

        next_question_key = self._next_missing_field(plant=updated_plant, user_memory=updated_memory)
        if next_question_key:
            updated_memory["pending_question"] = {
                "plant_id": updated_plant["id"],
                "question_key": next_question_key,
                "started_at": timestamp,
            }
            return {
                "handled": True,
                "memory": updated_memory,
                "plant": updated_plant,
                "rooms": updated_rooms,
                "response": f"Got it for {updated_plant['name']}. {self._question_text(next_question_key, updated_plant['name'])}",
            }

        updated_memory.pop("pending_question", None)
        return {
            "handled": True,
            "memory": updated_memory,
            "plant": updated_plant,
            "rooms": updated_rooms,
            "response": f"Thanks, I saved the watering profile for {updated_plant['name']}.",
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
            "plant_location": f"Where do you keep {plant_name}, and which city is it in? You can say something like 'indoors by the north window in Mumbai' or 'on the balcony in Bangalore'.",
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
            "plant_location": f"I still need the plant location for {plant_name}. Please mention indoor, balcony, or outdoor, and include the city if you can.",
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
        """Task: Parse room type, window direction, and city from a location answer.
        Input: A free-form user message.
        Output: A location payload dictionary, or None when parsing fails.
        Failures: No failure is expected.
        """

        lowered = message.lower()
        room_type = ""
        if "balcony" in lowered:
            room_type = "balcony"
        elif "outdoor" in lowered:
            room_type = "outdoor"
        elif "indoors" in lowered or "indoor" in lowered:
            room_type = "indoor"

        if not room_type:
            return None

        window_direction = ""
        for direction in ("north", "south", "east", "west"):
            if direction in lowered:
                window_direction = direction
                break

        city = ""
        for known_city in KNOWN_CITIES:
            if known_city in lowered:
                city = known_city.title()
                break

        room_name_parts = [room_type.capitalize()]
        if window_direction:
            room_name_parts.append(f"{window_direction.capitalize()} Window")
        room_name = " ".join(room_name_parts)

        return {
            "name": room_name,
            "type": room_type,
            "window_direction": window_direction,
            "city": city,
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
                "window_direction": location_payload.get("window_direction", ""),
                "size_sqft": "",
                "has_grow_light": "false",
                "city": location_payload.get("city", ""),
            }
            rooms.append(existing_room)
            return existing_room

        existing_room["type"] = location_payload["type"] or existing_room["type"]
        existing_room["window_direction"] = location_payload.get("window_direction", "") or existing_room["window_direction"]
        existing_room["city"] = location_payload.get("city", "") or existing_room["city"]
        return existing_room
