"""Conversational response generation for deterministic plant-care replies."""

from __future__ import annotations

from typing import Any


class ResponseGenerator:
    """Task: Build a plain conversational response from deterministic state and rule outputs.
    Input: Context, analysis, decisions, and the latest activity description.
    Output: A final assistant response string.
    Failures: No failure is expected; missing context yields a clarification response.
    """

    def generate(
        self,
        context: dict[str, Any],
        analysis: dict[str, Any],
        decisions: dict[str, list[str]],
        latest_activity: str,
        watering_schedule: dict[str, Any],
    ) -> str:
        """Task: Produce the final plain-text assistant reply.
        Input: The combined context, time-series analysis, decision output, and latest activity string.
        Output: A human-readable response string.
        Failures: No failure is expected.
        """

        plant = context.get("plant")
        if not plant:
            return "I could not determine which plant you mean yet. Mention the plant name or say you bought one."

        openers = [
            f"{plant['name']}: {latest_activity}",
            f"Here's the latest on {plant['name']}: {latest_activity}",
            f"Quick update for {plant['name']}: {latest_activity}",
        ]
        opener_index = sum(ord(character) for character in plant["id"]) % len(openers)
        parts = [openers[opener_index]]

        days_since_last_watered = watering_schedule.get("days_since_last_watered")
        watering_interval = watering_schedule.get("watering_interval_days")
        if days_since_last_watered is not None:
            parts.append(f"It has been {days_since_last_watered} day(s) since the last watering.")
        elif context.get("plant_requirements", {}).get("watering_interval_days"):
            suggested = context["plant_requirements"]["watering_interval_days"]
            parts.append(f"No watering history is stored yet. The starting interval for this plant is {suggested} day(s).")

        if watering_interval is not None:
            parts.append(f"The current watering interval is {watering_interval} day(s).")

        if watering_schedule.get("reminder_due"):
            parts.append(f"{plant['name']} is due for watering now.")

        notes = context.get("plant_requirements", {}).get("notes", [])
        if notes:
            parts.append(f"Care note: {notes[0]}")

        for recommendation in decisions.get("recommendations", []):
            parts.append(f"Guidance: {recommendation}")

        for warning in decisions.get("warnings", []):
            parts.append(f"Warning: {warning}")

        return " ".join(parts)
