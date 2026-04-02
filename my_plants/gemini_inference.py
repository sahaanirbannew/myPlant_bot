"""Gemini inference helper for the My Plants conversational layer."""

from __future__ import annotations

import os
from typing import Any

import httpx
from dotenv import load_dotenv


load_dotenv()


class GeminiInferenceClient:
    """Task: Call Gemini for My Plants response phrasing and contextual inference.
    Input: Environment configuration for the API key, model name, and API base URL.
    Output: A small client that can turn structured context into natural language.
    Failures: Missing credentials, network issues, or malformed Gemini responses can raise runtime exceptions.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        api_base_url: str | None = None,
    ) -> None:
        """Task: Initialize the Gemini inference client from explicit values or environment variables.
        Input: Optional API key, model name, and API base URL overrides.
        Output: A configured GeminiInferenceClient instance.
        Failures: No immediate failure is expected; runtime requests may fail if configuration is invalid.
        """

        self.api_key = (api_key or os.getenv("MY_PLANTS_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
        self.model = (model or os.getenv("MY_PLANTS_GEMINI_MODEL") or os.getenv("GEMINI_MODEL") or "gemini-2.5-flash").strip()
        self.api_base_url = (
            api_base_url
            or os.getenv("MY_PLANTS_GEMINI_API_BASE_URL")
            or os.getenv("GEMINI_API_BASE_URL")
            or "https://generativelanguage.googleapis.com/v1beta"
        ).rstrip("/")

    def is_configured(self) -> bool:
        """Task: Report whether the client has enough configuration to call Gemini.
        Input: No direct arguments.
        Output: True when an API key is present, otherwise False.
        Failures: No failure is expected.
        """

        return bool(self.api_key)

    def generate_text(self, prompt: str) -> str:
        """Task: Send a prompt to Gemini and return the generated text reply.
        Input: A prompt string containing persona instructions and structured context.
        Output: The first text response returned by Gemini.
        Failures: Raises runtime exceptions for HTTP failures or empty model output.
        """

        if not self.is_configured():
            raise RuntimeError("Gemini inference is not configured for My Plants.")

        url = f"{self.api_base_url}/models/{self.model}:generateContent"
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt,
                        }
                    ]
                }
            ]
        }

        with httpx.Client(timeout=30.0) as client:
            response = client.post(url, params={"key": self.api_key}, json=payload)
            response.raise_for_status()
            data = response.json()

        text = self._extract_text(data)
        if not text:
            raise ValueError("Gemini returned an empty My Plants response.")
        return text

    def _extract_text(self, payload: dict[str, Any]) -> str:
        """Task: Extract plain text from a Gemini API response payload.
        Input: The decoded JSON response body from Gemini.
        Output: A concatenated text string built from content parts.
        Failures: No failure is expected; returns an empty string if no text is present.
        """

        candidates = payload.get("candidates", [])
        for candidate in candidates:
            content = candidate.get("content", {})
            parts = content.get("parts", [])
            texts = [part.get("text", "") for part in parts if part.get("text")]
            if texts:
                return "\n".join(texts).strip()
        return ""
