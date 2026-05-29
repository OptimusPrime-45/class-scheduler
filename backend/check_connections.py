"""Quick connectivity check for the database and the Telegram bot.

Run from the backend/ directory so the local .env is picked up.

    # Check DB + verify the bot token (getMe), no message sent:
    python check_connections.py

    # Also send a real test message to your Telegram chat:
    python check_connections.py --chat-id 123456789

To find your chat ID: open your bot in Telegram, send it any message, then run
    python check_connections.py --show-updates
and copy the "id" from the chat that appears.

Exits 0 only if every attempted check succeeds.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import text

from app.config import settings
from app.db import engine


async def check_db() -> bool:
    """Open a real connection to Neon and run a trivial query."""
    print("DB  : connecting ...")
    try:
        async with engine.connect() as conn:
            value = (await conn.execute(text("SELECT 1"))).scalar_one()
            version = (await conn.execute(text("SELECT version()"))).scalar_one()
        assert value == 1
        print(f"DB  : OK  ({version.split(',')[0]})")
        return True
    except Exception as e:  # noqa: BLE001 - surface any failure to the user
        print(f"DB  : FAIL  {type(e).__name__}: {e}")
        return False
    finally:
        await engine.dispose()


async def check_telegram(chat_id: int | None, show_updates: bool) -> bool:
    """Verify the bot token and optionally send a real message / list updates."""
    print("BOT : connecting ...")
    if not settings.bot_token or settings.bot_token == "MOCK_TOKEN":
        print("BOT : SKIP  BOT_TOKEN not set in .env")
        return False

    # Import here so a missing token doesn't blow up at module load.
    from app.bot.webhook import bot

    try:
        me = await bot.get_me()
        print(f"BOT : OK  @{me.username} (id={me.id}, name={me.full_name})")

        if show_updates:
            updates = await bot.get_updates(limit=20)
            if not updates:
                print("BOT : no recent updates. Send your bot a message, then retry.")
            for u in updates:
                msg = u.message or u.edited_message
                if msg:
                    c = msg.chat
                    print(f"      chat_id={c.id}  type={c.type}  from={c.full_name or c.title}")

        if chat_id is not None:
            sent = await bot.send_message(
                chat_id=chat_id,
                text="✅ Tuition scheduler bot is connected. (test message)",
            )
            print(f"BOT : SENT test message to chat {chat_id} (message_id={sent.message_id})")

        return True
    except Exception as e:  # noqa: BLE001
        print(f"BOT : FAIL  {type(e).__name__}: {e}")
        return False
    finally:
        await bot.session.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description="DB + Telegram connectivity check")
    parser.add_argument("--chat-id", type=int, default=None,
                        help="Send a real test message to this Telegram chat ID.")
    parser.add_argument("--show-updates", action="store_true",
                        help="List recent updates so you can find your chat ID.")
    parser.add_argument("--skip-db", action="store_true", help="Skip the DB check.")
    args = parser.parse_args()

    db_ok = True if args.skip_db else await check_db()
    bot_ok = await check_telegram(args.chat_id, args.show_updates)
    print("-" * 40)
    print(f"Database : {'SKIPPED' if args.skip_db else ('OK' if db_ok else 'FAILED')}")
    print(f"Telegram : {'OK' if bot_ok else 'FAILED / SKIPPED'}")
    return 0 if (db_ok and bot_ok) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
