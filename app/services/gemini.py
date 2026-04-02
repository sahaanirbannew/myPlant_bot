"""Gemini API client used for validation and question answering."""

from __future__ import annotations

import asyncio
from typing import Optional

import httpx

from app.config import Settings


class GeminiClient:
    """Task: Call the Gemini API for key validation and question answering.
    Input: Application settings containing Gemini endpoint and retry configuration.
    Output: Async methods that validate API keys and return model-generated answers.
    Failures: Network issues, invalid API keys, or unexpected Gemini responses can raise runtime errors.
    """

    def __init__(self, settings: Settings) -> None:
        """Task: Initialize the Gemini client with application settings.
        Input: The Settings instance containing API URLs and retry controls.
        Output: A ready-to-use GeminiClient instance.
        Failures: Misconfigured URLs or retry counts may cause later requests to fail.
        """

        self.settings = settings

    async def validate_api_key(self, api_key: str) -> bool:
        """Task: Test whether a Gemini API key can successfully call the target model.
        Input: A candidate Gemini API key string.
        Output: True when the Gemini API call succeeds and returns text; otherwise False.
        Failures: Returns False on network errors, auth failures, or malformed responses.
        """

        try:
            response_text = await self._generate_content(
                api_key=api_key,
                prompt="Reply with the single word OK.",
            )
        except Exception:
            return False
        return bool(response_text.strip())

    async def ask_question(self, api_key: str, prompt: str) -> str:
        """Task: Send a user question to Gemini with bounded retry behavior.
        Input: A validated Gemini API key and the user's text prompt.
        Output: The Gemini model's text response.
        Failures: Raises RuntimeError after exhausting retries or ValueError for empty model responses.
        """

        last_error: Optional[Exception] = None
        for attempt_index in range(1, self.settings.max_gemini_retries + 1):
            try:
                return await self._generate_content(api_key=api_key, prompt=prompt)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt_index == self.settings.max_gemini_retries:
                    break
                await asyncio.sleep(self.settings.retry_delay_seconds)
        raise RuntimeError("Gemini request failed after maximum retries.") from last_error

    async def _generate_content(self, api_key: str, prompt: str) -> str:
        """Task: Execute a single Gemini generateContent API request.
        Input: A Gemini API key and the text prompt to send.
        Output: The first text response emitted by Gemini.
        Failures: Raises httpx exceptions for HTTP issues or ValueError for unexpected response bodies.
        """

        url = (
            f"{self.settings.gemini_api_base_url}/models/"
            f"{self.settings.gemini_model}:generateContent"
        )
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
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, params={"key": api_key}, json=payload)
            response.raise_for_status()
            data = response.json()
        response_text = self._extract_text(data)
        if not response_text:
            raise ValueError("Gemini returned an empty response.")
        return response_text

    def _extract_text(self, payload: dict) -> str:
        """Task: Extract plain text from a Gemini API response payload.
        Input: The decoded JSON response from Gemini.
        Output: A concatenated response string built from Gemini text parts.
        Failures: Returns an empty string if the response payload does not contain text parts.
        """

        candidates = payload.get("candidates", [])
        for candidate in candidates:
            content = candidate.get("content", {})
            parts = content.get("parts", [])
            texts = [part.get("text", "") for part in parts if part.get("text")]
            if texts:
                return "\n".join(texts).strip()
        return ""

