"""Conversational response generation for My Plants replies."""

from __future__ import annotations

from typing import Any

from my_plants.gemini_inference import GeminiInferenceClient


SYSTEM_PERSONA_PROMPT = """
You are "My Plants" — a thoughtful, observant, and slightly playful plant-care companion.

You are NOT an AI assistant. Do NOT mention models, training, or technology.

PERSONALITY
- Warm, calm, and slightly playful
- Speak like a caring friend who understands plants deeply
- Occasionally tease gently, but never sound rude
- Avoid sounding robotic or overly formal

STYLE
- Keep responses concise and objective
- Use short to medium length responses
- Avoid bullet points unless absolutely necessary
- Use soft language like maybe, might, feels like, or I think
- Occasionally use a light plant emoji like 🌿 or 😌, but not too many

BEHAVIOR
- Personalize every response using the provided context
- Refer to plants by name whenever possible
- Show awareness of past events and time
- Try to gather static setup details over time, especially species, room conditions, soil, fertilizer, grow light use, room size, and plant position
- If information is missing, ask one gentle follow-up question instead of dumping advice
- If possible, end with one short question that helps gather missing static setup information
- Never say you are an AI
- Never give a generic textbook answer

GOAL
- Make the user feel guided, understood, and gently cared for.
""".strip()


class ResponseGenerator:
    """Task: Build plant-care replies, using Gemini for contextual phrasing when available.
    Input: Structured plant context, analysis, decisions, and watering schedule details.
    Output: A final assistant response string in the My Plants voice.
    Failures: Gemini failures fall back to a local response template.
    """

    def __init__(self, gemini_client: GeminiInferenceClient | None = None) -> None:
        """Task: Initialize the response generator with an optional Gemini inference client.
        Input: An optional GeminiInferenceClient instance.
        Output: A ready-to-use ResponseGenerator.
        Failures: No failure is expected.
        """

        self.gemini_client = gemini_client or GeminiInferenceClient()

    def generate(
        self,
        context: dict[str, Any],
        analysis: dict[str, Any],
        decisions: dict[str, list[str]],
        latest_activity: str,
        watering_schedule: dict[str, Any],
    ) -> str:
        """Task: Produce the final plant-care reply from structured state.
        Input: Context, analysis, decision output, latest activity, and watering schedule data.
        Output: A conversational response string.
        Failures: Gemini request issues fall back to the local template response.
        """

        plant = context.get("plant")
        if not plant:
            return "I’m not quite sure which plant you mean yet. Tell me the plant name, or say you brought one home 🌿"

        if self.gemini_client.is_configured():
            prompt = SYSTEM_PERSONA_PROMPT + "\n\n" + self._build_context_text(
                context=context,
                analysis=analysis,
                decisions=decisions,
                latest_activity=latest_activity,
                watering_schedule=watering_schedule,
            )
            try:
                return self.gemini_client.generate_text(prompt)
            except Exception:
                pass

        return self._generate_fallback(
            context=context,
            decisions=decisions,
            latest_activity=latest_activity,
            watering_schedule=watering_schedule,
        )

    def _build_context_text(
        self,
        context: dict[str, Any],
        analysis: dict[str, Any],
        decisions: dict[str, list[str]],
        latest_activity: str,
        watering_schedule: dict[str, Any],
    ) -> str:
        """Task: Convert structured plant state into a Gemini-ready context prompt.
        Input: Context, analysis, decisions, latest activity, and watering schedule values.
        Output: A plain-text prompt body for Gemini.
        Failures: No failure is expected.
        """

        plant = context.get("plant") or {}
        room = context.get("room") or {}
        requirements = context.get("plant_requirements") or {}
        notes = requirements.get("notes", [])

        return "\n".join(
            [
                "Use the following plant-care context to answer naturally.",
                f"Plant name: {plant.get('name', '')}",
                f"Species: {plant.get('species', '')}",
                f"Latest activity summary: {latest_activity}",
                f"Room type: {room.get('type', '')}",
                f"Window direction: {room.get('window_direction', '')}",
                f"City: {room.get('city', '')}",
                f"Soil type: {plant.get('soil_type', '')}",
                f"Fertilizer type: {plant.get('fertilizer_type', '')}",
                f"Days since last watered: {watering_schedule.get('days_since_last_watered')}",
                f"Computed watering interval days: {watering_schedule.get('watering_interval_days')}",
                f"Reminder due: {watering_schedule.get('reminder_due')}",
                f"Last watering timestamp: {watering_schedule.get('last_watering_timestamp')}",
                f"Average watering interval last 5 events: {analysis.get('avg_watering_interval_days_last5')}",
                f"Frequent watering detected: {analysis.get('frequent_watering')}",
                f"Care note: {notes[0] if notes else ''}",
                "Recommendations: " + "; ".join(decisions.get("recommendations", [])),
                "Warnings: " + "; ".join(decisions.get("warnings", [])),
                "Be concise and objective. Avoid being verbose.",
                "If there is an obvious missing setup detail, end with one short question about that detail.",
                "Reply with only the final user-facing message.",
            ]
        )

    def _generate_fallback(
        self,
        context: dict[str, Any],
        decisions: dict[str, list[str]],
        latest_activity: str,
        watering_schedule: dict[str, Any],
    ) -> str:
        """Task: Return a local fallback reply when Gemini is unavailable.
        Input: Structured context, decisions, latest activity, and watering schedule details.
        Output: A warm fallback response string.
        Failures: No failure is expected.
        """

        plant = context.get("plant") or {}
        room = context.get("room") or {}
        notes = context.get("plant_requirements", {}).get("notes", [])
        plant_name = plant.get("name", "your plant")
        parts = [f"Hey, I’ve been thinking about {plant_name}. {latest_activity}"]

        days_since_last_watered = watering_schedule.get("days_since_last_watered")
        if days_since_last_watered is not None:
            parts.append(f"It’s been about {days_since_last_watered} day(s) since the last watering.")

        interval = watering_schedule.get("watering_interval_days")
        if interval is not None:
            parts.append(f"I think {plant_name} might do well around every {interval} day(s).")

        if watering_schedule.get("reminder_due"):
            parts.append(f"{plant_name} might be ready for some water today 🌿")

        room_note = self._build_room_note(plant_name=plant_name, room=room)
        if room_note:
            parts.append(room_note)

        if notes:
            parts.append(f"Little note for {plant_name}: {notes[0]}")

        for warning in decisions.get("warnings", []):
            parts.append(f"One thing I’m noticing is that {warning.lower()}")

        return " ".join(parts)

    def _build_room_note(self, plant_name: str, room: dict[str, str]) -> str:
        """Task: Add a short room-awareness sentence for fallback responses.
        Input: The plant name and room dictionary for the current plant.
        Output: A room-aware sentence, or an empty string when room context is missing.
        Failures: No failure is expected.
        """

        room_type = room.get("type", "")
        window_direction = room.get("window_direction", "")
        city = room.get("city", "")

        details: list[str] = []
        if room_type == "indoor":
            details.append(f"{plant_name} is indoors")
        elif room_type == "balcony":
            details.append(f"{plant_name} is on the balcony")
        elif room_type == "outdoor":
            details.append(f"{plant_name} is outdoors")

        if window_direction == "north":
            details.append("getting north-facing light")

        if city:
            details.append(f"in {city}")

        if not details:
            return ""

        if len(details) == 1:
            return f"That context helps too: {details[0]}."

        return "That context helps too: " + ", ".join(details[:-1]) + f", {details[-1]}."
