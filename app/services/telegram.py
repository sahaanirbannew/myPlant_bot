"""Telegram Bot API client helpers."""

from __future__ import annotations

import httpx


class TelegramClient:
    """Task: Send outbound messages and webhook configuration calls to Telegram.
    Input: The Telegram bot token used to authenticate Bot API requests.
    Output: Async helpers for sending messages and registering the webhook.
    Failures: Network issues or invalid bot tokens can raise HTTP-related exceptions.
    """

    def __init__(self, bot_token: str) -> None:
        """Task: Initialize the Telegram client with the bot token.
        Input: A Telegram bot token string.
        Output: A ready-to-use TelegramClient instance.
        Failures: An empty or invalid token will cause later API calls to fail.
        """

        self.base_url = f"https://api.telegram.org/bot{bot_token}"

    async def send_message(self, chat_id: int, text: str) -> None:
        """Task: Deliver a text message to a Telegram chat.
        Input: A chat id and the message text to send.
        Output: None; Telegram accepts the outbound message request.
        Failures: Raises httpx exceptions if Telegram rejects the request or is unreachable.
        """

        payload = {
            "chat_id": chat_id,
            "text": text,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(f"{self.base_url}/sendMessage", json=payload)
            response.raise_for_status()

    async def set_webhook(self, webhook_url: str) -> dict:
        """Task: Register the FastAPI webhook URL with Telegram.
        Input: The publicly reachable HTTPS webhook URL.
        Output: The decoded Telegram API response body.
        Failures: Raises httpx exceptions if Telegram rejects the webhook registration.
        """

        payload = {
            "url": webhook_url,
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(f"{self.base_url}/setWebhook", json=payload)
            response.raise_for_status()
            return response.json()

