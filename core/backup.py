import asyncio
import io
import logging
import os
import shutil
import sqlite3
import subprocess
import tempfile
import zipfile
from datetime import timedelta

from aiogram import Bot
from aiogram.types import FSInputFile
from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.utils import timezone

from core.jalali import to_jalali_datetime
from core.models import BotSetting
from core.services import get_all_admin_ids

logger = logging.getLogger(__name__)

_BACKUP_LOCK = asyncio.Lock()


def get_backup_storage_dir() -> str:
    backup_dir = os.path.join(
        str(settings.BASE_DIR),
        "backups",
    )
    os.makedirs(
        backup_dir,
        exist_ok=True,
    )
    return backup_dir


def cleanup_old_backup_files(
    backup_dir: str,
    keep_path: str | None = None,
):
    for entry in os.listdir(backup_dir):
        if not entry.endswith(".zip"):
            continue
        full_path = os.path.join(
            backup_dir,
            entry,
        )
        if keep_path and os.path.abspath(full_path) == os.path.abspath(keep_path):
            continue
        try:
            os.remove(full_path)
        except OSError:
            pass


@sync_to_async
def get_backup_runtime_state() -> tuple[bool, int, timezone.datetime | None, dict]:
    setting, _ = BotSetting.objects.get_or_create(id=1)
    return (
        bool(setting.backup_enabled),
        max(1, int(setting.backup_interval_minutes or 5)),
        setting.last_backup_at,
        dict(setting.last_backup_messages or {}),
    )


@sync_to_async
def update_backup_runtime_state(
    msg_map: dict[str, int],
):
    BotSetting.objects.filter(id=1).update(
        last_backup_at=timezone.now(),
        last_backup_messages=msg_map,
    )


@sync_to_async
def create_full_backup_zip_sync() -> tuple[str, str, int, str]:
    backup_dir = get_backup_storage_dir()
    cleanup_old_backup_files(backup_dir)

    ts_label = timezone.localtime(timezone.now()).strftime("%Y%m%d_%H%M%S")
    zip_filename = f"pomo_backup_{ts_label}.zip"
    zip_path = os.path.join(
        backup_dir,
        zip_filename,
    )

    db_conf = connection.settings_dict
    db_engine = str(db_conf.get("ENGINE") or "").lower()
    db_label = "SQLite" if "sqlite" in db_engine else "PostgreSQL"

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_dump_files: list[tuple[str, str]] = []

        if "sqlite" in db_engine:
            db_path = str(db_conf.get("NAME") or "")
            if db_path and os.path.exists(db_path):
                sqlite_copy_path = os.path.join(
                    tmp_dir,
                    "db.sqlite3",
                )
                src_conn = sqlite3.connect(db_path)
                dst_conn = sqlite3.connect(sqlite_copy_path)
                try:
                    src_conn.backup(dst_conn)
                finally:
                    dst_conn.close()
                    src_conn.close()
                db_dump_files.append((sqlite_copy_path, "db.sqlite3"))

        elif "postgresql" in db_engine or "postgis" in db_engine:
            pg_dump_bin = shutil.which("pg_dump")
            if pg_dump_bin:
                sql_path = os.path.join(
                    tmp_dir,
                    "database.sql",
                )
                env = os.environ.copy()
                env["PGPASSWORD"] = str(db_conf.get("PASSWORD") or "")
                cmd = [
                    pg_dump_bin,
                    "--clean",
                    "--if-exists",
                    "--no-owner",
                    "--no-acl",
                    "-f",
                    sql_path,
                ]
                if db_conf.get("HOST"):
                    cmd.extend(["-h", str(db_conf["HOST"])])
                if db_conf.get("PORT"):
                    cmd.extend(["-p", str(db_conf["PORT"])])
                if db_conf.get("USER"):
                    cmd.extend(["-U", str(db_conf["USER"])])
                if db_conf.get("NAME"):
                    cmd.extend(["-d", str(db_conf["NAME"])])

                try:
                    subprocess.run(
                        cmd,
                        env=env,
                        check=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=60,
                    )
                    if os.path.exists(sql_path):
                        db_dump_files.append((sql_path, "database.sql"))
                except Exception as exc:
                    logger.warning(f"pg_dump failed, falling back to dumpdata: {exc}")

        json_dump_path = os.path.join(
            tmp_dir,
            "database_django.json",
        )
        json_buf = io.StringIO()
        call_command(
            "dumpdata",
            exclude=[
                "contenttypes",
                "auth.permission",
                "sessions",
                "admin.logentry",
            ],
            natural_foreign=True,
            natural_primary=True,
            indent=2,
            stdout=json_buf,
        )
        with open(
            json_dump_path,
            "w",
            encoding="utf-8",
        ) as jf:
            jf.write(json_buf.getvalue())
        db_dump_files.append((json_dump_path, "database_django.json"))

        with zipfile.ZipFile(
            zip_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as zf:
            for src_file, arc_name in db_dump_files:
                zf.write(
                    src_file,
                    arcname=arc_name,
                )

            media_root = str(settings.MEDIA_ROOT)
            if os.path.exists(media_root):
                for root, _, files in os.walk(media_root):
                    for fname in files:
                        abs_media_file = os.path.join(
                            root,
                            fname,
                        )
                        rel_media_path = os.path.relpath(
                            abs_media_file,
                            media_root,
                        )
                        zf.write(
                            abs_media_file,
                            arcname=os.path.join("media", rel_media_path),
                        )

    size_bytes = os.path.getsize(zip_path)
    return zip_path, zip_filename, size_bytes, db_label


async def send_backup_to_admins(
    bot: Bot,
) -> tuple[bool, str]:
    async with _BACKUP_LOCK:
        try:
            _, interval_mins, _, prev_msg_map = await get_backup_runtime_state()
            zip_path, zip_filename, size_bytes, db_label = await create_full_backup_zip_sync()
        except Exception as exc:
            logger.exception(f"Failed to build backup zip: {exc}")
            return False, f"خطا در ساخت فایل بکاپ: {exc}"

        max_tg_bytes = 49 * 1024 * 1024
        if size_bytes > max_tg_bytes:
            size_mb = size_bytes / (1024 * 1024)
            return (
                False,
                f"حجم فایل بکاپ ({size_mb:.1f} مگابایت) از سقف مجاز تلگرام (۵۰ مگابایت) بیشتر است.",
            )

        admin_ids = await get_all_admin_ids()
        if not admin_ids:
            return False, "هیچ ادمینی برای ارسال بکاپ یافت نشد."

        rlm = "\u200f"
        size_str = (
            f"{size_bytes / (1024 * 1024):.2f} مگابایت"
            if size_bytes >= 1024 * 1024
            else f"{max(1, round(size_bytes / 1024))} کیلوبایت"
        )
        now_j = to_jalali_datetime(timezone.now())
        date_str = now_j.strftime("%Y/%m/%d") if now_j else "—"
        time_str = now_j.strftime("%H:%M") if now_j else "—"

        caption = (
            f"{rlm}🗄 <b>بکاپ کامل سیستم (دیتابیس + مدیا)</b>\n"
            f"{rlm}📅 تاریخ: <b>{date_str}</b> | ساعت: <b>{time_str}</b>\n"
            f"{rlm}💾 موتور دیتابیس: <b>{db_label}</b>\n"
            f"{rlm}📦 حجم فایل: <b>{size_str}</b>\n"
            f"{rlm}⏱ دوره فعلی: <b>هر {interval_mins} دقیقه</b>\n\n"
            f"{rlm}<i>فایل بکاپ قبلی به صورت خودکار پاک شد.</i>"
        )

        new_msg_map: dict[str, int] = {}
        sent_count = 0

        for aid in admin_ids:
            aid_key = str(aid)
            prev_msg_id = prev_msg_map.get(aid_key)
            if prev_msg_id:
                try:
                    await bot.delete_message(
                        chat_id=aid,
                        message_id=int(prev_msg_id),
                    )
                except Exception:
                    pass

            try:
                sent_msg = await bot.send_document(
                    chat_id=aid,
                    document=FSInputFile(
                        zip_path,
                        filename=zip_filename,
                    ),
                    caption=caption,
                    parse_mode="HTML",
                )
                new_msg_map[aid_key] = sent_msg.message_id
                sent_count += 1
            except Exception as exc:
                logger.warning(f"Failed to send backup to admin {aid}: {exc}")

        await update_backup_runtime_state(new_msg_map)
        return True, f"بکاپ ({size_str}) با موفقیت به {sent_count} ادمین ارسال شد."


async def backup_scheduler_loop(bot: Bot):
    await asyncio.sleep(10)
    while True:
        try:
            enabled, interval_mins, last_at, _ = await get_backup_runtime_state()
            if enabled:
                now = timezone.now()
                is_due = (
                    last_at is None
                    or (now - last_at) >= timedelta(minutes=interval_mins)
                )
                if is_due:
                    await send_backup_to_admins(bot)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(f"Backup scheduler loop error: {exc}")

        await asyncio.sleep(30)