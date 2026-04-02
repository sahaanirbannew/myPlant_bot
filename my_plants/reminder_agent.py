"""Reminder scanning and friendly due-plant messaging."""

from __future__ import annotations

from typing import Any


class ReminderAgent:
    """Task: Scan plant schedules for a user and generate grouped reminder messages for due plants.
    Input: Due-plant schedules and current timestamp metadata.
    Output: Friendly reminder strings that feel less repetitive.
    Failures: No failure is expected.
    """

    def generate(self, due_plants: list[dict[str, Any]], now_timestamp: str) -> str:
        """Task: Generate a deterministic, friendly reminder message for all due plants.
        Input: A list of due plant payloads and the current timestamp.
        Output: A reminder message string.
        Failures: No failure is expected.
        """

        if not due_plants:
            return "Nothing is due for watering right now. Your plants look on schedule."

        plant_names = [item["plant"]["name"] for item in due_plants]
        template_index = sum(ord(character) for character in now_timestamp) % 3

        if len(plant_names) == 1:
            plant = due_plants[0]
            plant_name = plant["plant"]["name"]
            days = plant["schedule"]["days_since_last_watered"]
            templates = [
                f"It's time to water your {plant_name}.",
                f"Remember your {plant_name}? It's been {days} day(s) since the last watering.",
                f"Your {plant_name} is due for a drink today.",
            ]
            return templates[template_index]

        joined_names = self._join_names(plant_names)
        templates = [
            f"It's time you water your {joined_names}.",
            f"Your {joined_names} are due for watering today.",
            f"Quick plant check: {joined_names} are ready for watering.",
        ]
        return templates[template_index]

    def _join_names(self, names: list[str]) -> str:
        """Task: Join plant names into a natural language list.
        Input: A list of plant name strings.
        Output: A comma-separated natural-language list.
        Failures: No failure is expected.
        """

        if len(names) == 2:
            return f"{names[0]} and {names[1]}"
        return ", ".join(names[:-1]) + f", and {names[-1]}"
