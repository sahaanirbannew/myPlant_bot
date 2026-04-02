"""Personalized watering-interval calculation."""

from __future__ import annotations

from typing import Any


SOIL_ADJUSTMENTS = {
    "cocopeat": -1,
    "potting mix": 0,
    "succulent mix": 3,
    "sandy soil": -1,
    "loamy soil": 0,
    "clay soil": 1,
}

ROOM_ADJUSTMENTS = {
    "indoor": 1,
    "balcony": 0,
    "outdoor": -1,
}

HUMIDITY_ADJUSTMENTS = {
    "high": 1,
    "medium": 0,
    "low": -1,
}

TEMPERATURE_ADJUSTMENTS = {
    "hot": -1,
    "warm": 0,
    "moderate": 0,
    "cool": 1,
}


class WateringScheduler:
    """Task: Compute personalized watering intervals and due-state reminders from deterministic inputs.
    Input: Plant, room, user memory, requirements, city profiles, and time-series metrics.
    Output: Watering interval details and reminder status for a plant.
    Failures: No failure is expected; missing values fall back to conservative defaults.
    """

    def compute(self, context: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
        """Task: Calculate the effective watering interval and due reminder state for a plant.
        Input: The combined context dictionary and time-series analysis output.
        Output: Interval, days-since-watered, reminder flag, and calculation details.
        Failures: No failure is expected.
        """

        plant = context.get("plant") or {}
        room = context.get("room") or {}
        memory = context.get("memory") or {}
        plant_requirements = context.get("plant_requirements") or {}
        city_profiles = context.get("city_profiles") or {}
        plant_preferences = memory.get("plant_preferences", {}).get(plant.get("id", ""), {})

        base_interval = int(plant_requirements.get("watering_interval_days", 7))
        user_defined_interval = plant_preferences.get("user_defined_watering_interval_days")
        history_interval = analysis.get("avg_watering_interval_days_last5")

        if user_defined_interval:
            final_interval = float(user_defined_interval)
            source = "user_defined"
        else:
            adjusted_base = float(base_interval)
            adjusted_base += ROOM_ADJUSTMENTS.get(room.get("type", ""), 0)
            adjusted_base += SOIL_ADJUSTMENTS.get(plant.get("soil_type", "").lower(), 0)

            city_key = room.get("city", "").lower()
            city_profile = city_profiles.get(city_key, city_profiles.get("default", {}))
            adjusted_base += HUMIDITY_ADJUSTMENTS.get(city_profile.get("humidity", "medium"), 0)
            adjusted_base += TEMPERATURE_ADJUSTMENTS.get(city_profile.get("temperature_band", "moderate"), 0)
            adjusted_base = max(adjusted_base, 1)

            if history_interval is not None:
                final_interval = round((adjusted_base + float(history_interval)) / 2, 1)
                source = "blended_base_and_history"
            else:
                final_interval = adjusted_base
                source = "adjusted_base"

        days_since_last_watered = analysis.get("days_since_last_watered")
        reminder_due = bool(days_since_last_watered is not None and days_since_last_watered >= final_interval)

        return {
            "watering_interval_days": final_interval,
            "days_since_last_watered": days_since_last_watered,
            "last_watering_timestamp": analysis.get("last_watering_timestamp"),
            "reminder_due": reminder_due,
            "interval_source": source,
        }
