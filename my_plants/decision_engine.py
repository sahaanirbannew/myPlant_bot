"""Rule-based plant-care decision engine."""

from __future__ import annotations

from typing import Any


class DecisionEngine:
    """Task: Convert context and time-series analysis into deterministic care guidance.
    Input: The combined context dictionary and watering metrics.
    Output: Warnings and recommendations for the response generator.
    Failures: No failure is expected; missing fields simply reduce the number of generated rules.
    """

    def evaluate(self, context: dict[str, Any], analysis: dict[str, Any]) -> dict[str, list[str]]:
        """Task: Apply simple plant-care rules based on room and event conditions.
        Input: The combined context object and time-series analysis output.
        Output: A dictionary containing warnings and recommendations.
        Failures: No failure is expected.
        """

        room = context.get("room") or {}
        recommendations: list[str] = []
        warnings: list[str] = []

        if room.get("type") == "indoor":
            recommendations.append("Indoor placement usually means watering should be less frequent.")

        if room.get("window_direction") == "north":
            recommendations.append("A north-facing window usually means lower light conditions.")

        if analysis.get("frequent_watering"):
            warnings.append("Recent watering frequency suggests possible overwatering.")

        return {
            "warnings": warnings,
            "recommendations": recommendations,
        }

