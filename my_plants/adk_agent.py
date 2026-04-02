"""ADK-facing wrapper for the deterministic My Plants backend."""

from __future__ import annotations

from typing import Any

from my_plants.orchestrator import build_default_orchestrator


try:
    from google.adk.agents import BaseAgent

    GOOGLE_ADK_AVAILABLE = True
    ADK_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # noqa: BLE001
    GOOGLE_ADK_AVAILABLE = False
    ADK_IMPORT_ERROR = exc

    class BaseAgent:  # type: ignore[override]
        """Task: Provide a minimal fallback base class when google-adk is unavailable.
        Input: Arbitrary keyword arguments passed during deterministic local use.
        Output: A lightweight object that mimics an agent wrapper.
        Failures: No failure is expected.
        """

        def __init__(self, **_: Any) -> None:
            """Task: Accept arbitrary construction keywords without performing ADK runtime behavior.
            Input: Any keyword arguments.
            Output: A constructed fallback BaseAgent.
            Failures: No failure is expected.
            """

            return


class MyPlantsAgent(BaseAgent):
    """Task: Expose the deterministic My Plants orchestrator behind an ADK-compatible wrapper.
    Input: User id and message text passed into the `handle` method.
    Output: Deterministic plant-care responses generated from local files.
    Failures: Runtime file issues from the orchestrator can propagate as exceptions.
    """

    def __init__(self) -> None:
        """Task: Initialize the ADK wrapper with the default deterministic orchestrator.
        Input: No direct arguments.
        Output: A ready-to-use MyPlantsAgent instance.
        Failures: No failure is expected during normal construction.
        """

        super().__init__(name="my_plants_agent", description="Deterministic plant care assistant")
        self.orchestrator = build_default_orchestrator()

    def handle(self, user_id: str, message: str) -> str:
        """Task: Route a message into the deterministic My Plants backend.
        Input: The user id and raw user message text.
        Output: The backend response string.
        Failures: File IO and parsing issues from the orchestrator can raise runtime exceptions.
        """

        return self.orchestrator.handle(user_id=user_id, message=message)


def build_agent() -> MyPlantsAgent:
    """Task: Construct the My Plants ADK wrapper agent.
    Input: No direct arguments.
    Output: A MyPlantsAgent instance.
    Failures: No failure is expected during normal construction.
    """

    return MyPlantsAgent()

