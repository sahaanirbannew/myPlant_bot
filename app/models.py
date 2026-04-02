"""Pydantic models used by the Telegram webhook endpoint."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class TelegramUser(BaseModel):
    """Task: Represent a Telegram user payload from the Telegram Bot API.
    Input: JSON fields delivered by Telegram for a user object.
    Output: A validated TelegramUser model instance.
    Failures: Validation fails if Telegram omits required numeric identifiers.
    """

    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None


class TelegramChat(BaseModel):
    """Task: Represent the chat payload attached to a Telegram message.
    Input: JSON fields delivered by Telegram for a chat object.
    Output: A validated TelegramChat model instance.
    Failures: Validation fails if the chat identifier is missing.
    """

    id: int
    type: str


class TelegramMessage(BaseModel):
    """Task: Represent an incoming Telegram message that may contain text.
    Input: JSON fields delivered by Telegram for a message object.
    Output: A validated TelegramMessage model instance.
    Failures: Validation fails if Telegram omits required nested user or chat data.
    """

    message_id: int
    date: int
    chat: TelegramChat
    from_user: TelegramUser = Field(alias="from")
    text: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)


class TelegramUpdate(BaseModel):
    """Task: Represent the top-level Telegram update payload.
    Input: JSON fields delivered by Telegram for an update.
    Output: A validated TelegramUpdate model instance.
    Failures: Validation fails if the update shape differs from the supported Telegram schema.
    """

    update_id: int
    message: Optional[TelegramMessage] = None
