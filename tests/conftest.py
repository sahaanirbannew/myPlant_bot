"""Pytest configuration for local package imports."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
import re
from typing import Any

@pytest.fixture(autouse=True)
def mock_extract_with_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_extract_with_llm(self_instance: Any, message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        lowered = message.lower()
        if context and context.get("pending_question") == "soil_type":
            for soil in ["cocopeat", "potting mix", "sand", "succulent mix", "sandy soil", "loamy soil", "clay soil"]:
                if soil in lowered:
                    return {"soil_type": soil}
            return {"soil_type": message.strip()}
            
        if context and context.get("pending_question") == "watering_frequency":
            match = re.search(r"(\d+)", lowered)
            if match:
                return {"days": int(match.group(1))}
            if "every day" in lowered or "daily" in lowered:
                return {"days": 1}
            return {}
            
        if context and context.get("pending_question") == "plant_location":
            room = "indoor room" if "indoor" in lowered else "bedroom" if "bedroom" in lowered else "balcony" if "balcony" in lowered else "living room"
            windows = "north" if "north" in lowered else "south" if "south" in lowered else ""
            return {"room": room, "windows": windows}
            
        return {}

    from my_plants.gemini_inference import GeminiInferenceClient
    monkeypatch.setattr(GeminiInferenceClient, "extract_with_llm", fake_extract_with_llm)
