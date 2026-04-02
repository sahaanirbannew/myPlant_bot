"""Reminder scanning and due-plant messaging."""

from __future__ import annotations

from typing import Any

from my_plants.gemini_inference import GeminiInferenceClient
from my_plants.response_generator import SYSTEM_PERSONA_PROMPT


class ReminderAgent:
    """Task: Generate due-plant reminders, using Gemini for natural phrasing when available.
    Input: Due-plant schedule payloads and the current timestamp metadata.
    Output: A reminder string for the user.
    Failures: Gemini failures fall back to local reminder templates.
    """

    def __init__(self, gemini_client: GeminiInferenceClient | None = None) -> None:
        """Task: Initialize the reminder agent with an optional Gemini inference client.
        Input: An optional GeminiInferenceClient instance.
        Output: A ready-to-use ReminderAgent.
        Failures: No failure is expected.
        """

        self.gemini_client = gemini_client or GeminiInferenceClient()

    def generate(self, due_plants: list[dict[str, Any]], now_timestamp: str) -> str:
        """Task: Generate a reminder message for due plants.
        Input: A list of due-plant payloads and the current timestamp string.
        Output: A reminder response string.
        Failures: Gemini request issues fall back to the local reminder template.
        """

        if not due_plants:
            return "Nothing feels due for water just yet. Your little jungle seems nicely on track 😌"

        if self.gemini_client.is_configured():
            prompt = SYSTEM_PERSONA_PROMPT + "\n\n" + self._build_context_text(due_plants=due_plants, now_timestamp=now_timestamp)
            try:
                return self.gemini_client.generate_text(prompt)
            except Exception:
                pass

        return self._generate_fallback(due_plants=due_plants, now_timestamp=now_timestamp)

    def _build_context_text(self, due_plants: list[dict[str, Any]], now_timestamp: str) -> str:
        """Task: Build a Gemini prompt body for reminder generation.
        Input: Due-plant payloads and the current timestamp.
        Output: A plain-text prompt describing which plants are due.
        Failures: No failure is expected.
        """

        lines = [
            "Write one short user-facing watering reminder message.",
            f"Current timestamp: {now_timestamp}",
            "Plants due for watering:",
        ]
        for item in due_plants:
            plant = item.get("plant", {})
            schedule = item.get("schedule", {})
            lines.append(
                f"- {plant.get('name', '')}: days since last watered={schedule.get('days_since_last_watered')}, interval={schedule.get('watering_interval_days')}"
            )
        lines.append("Keep it warm, natural, and gently nudging. Reply with only the final message.")
        return "\n".join(lines)

    def _generate_fallback(self, due_plants: list[dict[str, Any]], now_timestamp: str) -> str:
        """Task: Return a local reminder message when Gemini is unavailable.
        Input: Due-plant payloads and the current timestamp string.
        Output: A fallback reminder message string.
        Failures: No failure is expected.
        """

        plant_names = [item["plant"]["name"] for item in due_plants]
        template_index = sum(ord(character) for character in now_timestamp) % 3

        if len(plant_names) == 1:
            plant = due_plants[0]
            plant_name = plant["plant"]["name"]
            days = plant["schedule"]["days_since_last_watered"]
            templates = [
                f"Hey… {plant_name} might be ready for some water today 🌿",
                f"Remember {plant_name}? It’s been about {days} day(s) since the last drink.",
                f"I think {plant_name} is starting to feel a little thirsty.",
            ]
            return templates[template_index]

        joined_names = self._join_names(plant_names)
        templates = [
            f"Hey… {joined_names} might be ready for some water today 🌿",
            f"I think {joined_names} are due for a drink.",
            f"Little nudge: {joined_names} seem ready for watering.",
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
