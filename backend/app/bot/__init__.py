from __future__ import annotations

from app.bot.webhook import bot, dp, bot_router
from app.bot.polls import router as polls_router, send_availability_poll
from app.bot.notify import send_schedule_notifications

# Register polls router with the Dispatcher
dp.include_router(polls_router)

__all__ = [
    "bot",
    "dp",
    "bot_router",
    "polls_router",
    "send_availability_poll",
    "send_schedule_notifications",
]
