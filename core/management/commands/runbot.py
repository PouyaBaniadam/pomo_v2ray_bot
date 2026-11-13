import asyncio
import logging
from django.core.management.base import BaseCommand
from django.conf import settings
from aiogram import (
    Bot,
    Dispatcher,
)
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import (
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
)
from aiogram.fsm.storage.memory import MemoryStorage

from bot.middlewares import (
    RateLimitMiddleware,
    UserUpsertAndAntiLoopMiddleware,
)
from bot.handlers.common import router as common_router
from bot.handlers.wallet import router as wallet_router
from bot.handlers.buy import router as buy_router
from bot.handlers.services import router as services_router
from bot.handlers.gifts import router as gifts_router
from bot.handlers.admin_panel import router as admin_panel_router
from core.backup import backup_scheduler_loop
from core.services import get_all_admin_ids


class Command(BaseCommand):
    help = "Run the Telegram bot using Aiogram 3.x."

    def handle(
        self,
        *args,
        **options,
    ):
        logging.basicConfig(level=logging.INFO)
        if not settings.BOT_TOKEN or settings.BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
            self.stdout.write(
                self.style.ERROR("Error: BOT_TOKEN is not configured in .env.")
            )
            return

        asyncio.run(
            self.start_bot(),
        )

    async def start_bot(self):
        if settings.REDIS_URL:
            from aiogram.fsm.storage.redis import RedisStorage
            storage = RedisStorage.from_url(
                settings.REDIS_URL,
            )
            self.stdout.write(
                self.style.SUCCESS("Connected to Redis storage.")
            )
        else:
            storage = MemoryStorage()
            self.stdout.write(
                self.style.WARNING("Using in-memory FSM storage.")
            )

        session = None
        if getattr(settings, 'PROXY_URL', ''):
            session = AiohttpSession(
                proxy=settings.PROXY_URL,
            )
            self.stdout.write(
                self.style.SUCCESS(f"Using proxy: {settings.PROXY_URL}")
            )

        bot = Bot(
            token=settings.BOT_TOKEN,
            session=session,
        )
        dp = Dispatcher(
            storage=storage,
        )

        dp.message.middleware(
            RateLimitMiddleware(),
        )
        dp.callback_query.middleware(
            RateLimitMiddleware(),
        )
        dp.message.middleware(
            UserUpsertAndAntiLoopMiddleware(),
        )
        dp.callback_query.middleware(
            UserUpsertAndAntiLoopMiddleware(),
        )

        dp.include_router(admin_panel_router)
        dp.include_router(common_router)
        dp.include_router(wallet_router)
        dp.include_router(buy_router)
        dp.include_router(services_router)
        dp.include_router(gifts_router)

        await bot.set_my_commands(
            commands=[
                BotCommand(
                    command="start",
                    description="شروع مجدد 🔄",
                )
            ],
            scope=BotCommandScopeDefault(),
        )

        admin_ids = await get_all_admin_ids()
        admin_count = 0
        for aid in admin_ids:
            try:
                await bot.set_my_commands(
                    commands=[
                        BotCommand(
                            command="start",
                            description="شروع مجدد 🔄",
                        ),
                        BotCommand(
                            command="admin",
                            description="پنل مدیریت تلگرام 🛠",
                        ),
                    ],
                    scope=BotCommandScopeChat(
                        chat_id=aid,
                    ),
                )
                admin_count += 1
            except Exception:
                pass

        self.stdout.write(
            self.style.SUCCESS(f"Bot started successfully (Admin menu registered for {admin_count} admins).")
        )
        await bot.delete_webhook(
            drop_pending_updates=True,
        )

        backup_task = asyncio.create_task(backup_scheduler_loop(bot))
        try:
            await dp.start_polling(bot)
        finally:
            backup_task.cancel()
            try:
                await backup_task
            except asyncio.CancelledError:
                pass