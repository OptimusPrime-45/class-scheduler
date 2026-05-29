from __future__ import annotations

import logging
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from fastapi import APIRouter, HTTPException, Request, status

from app.config import settings

logger = logging.getLogger(__name__)

# Format token to satisfy aiogram validation
bot_token = settings.bot_token
if not bot_token or bot_token == "MOCK_TOKEN":
    bot_token = "123456789:MOCK_TOKEN"

bot = Bot(token=bot_token)
dp = Dispatcher()

bot_router = APIRouter()


@bot_router.post("/api/bot/webhook")
async def telegram_webhook(request: Request):
    """Secure endpoint for Telegram webhook updates."""
    secret_token = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if settings.telegram_webhook_secret and secret_token != settings.telegram_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid secret token",
        )

    try:
        update_data = await request.json()
        update = Update.model_validate(update_data)
        await dp.feed_update(bot, update)
    except Exception as e:
        logger.exception("Error processing webhook update")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to process update: {e}",
        )

    return {"status": "ok"}
