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
from aiogram.client.session.aiohttp import AiohttpSession
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
MAX_ZIP_PART_BYTES = 48 * 1024 * 1024


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
):
    if not os.path.exists(backup_dir):
        return
    for entry in os.listdir(backup_dir):
        if not entry.endswith(".zip"):
            continue
        full_path = os.path.join(
            backup_dir,
            entry,
        )
        try:
            os.remove(full_path)
        except OSError:
            pass


def format_file_size_fa(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} مگابایت"
    return f"{max(1, round(size_bytes / 1024))} کیلوبایت"


@sync_to_async
def get_backup_runtime_state() -> tuple[bool, int, timezone.datetime | None]:
    setting, _ = BotSetting.objects.get_or_create(id=1)
    return (
        bool(setting.backup_enabled),
        max(1, int(setting.backup_interval_minutes or 5)),
        setting.last_backup_at,
    )


@sync_to_async
def update_backup_runtime_timestamp():
    BotSetting.objects.filter(id=1).update(
        last_backup_at=timezone.now(),
    )


@sync_to_async
def create_split_backup_archives_sync() -> dict:
    backup_dir = get_backup_storage_dir()
    cleanup_old_backup_files(backup_dir)

    now_local = timezone.localtime(timezone.now())
    ts_label = now_local.strftime("%Y%m%d_%H%M%S")
    batch_code = f"BKP_{ts_label}"

    db_zip_filename = f"pomo_db_{ts_label}.zip"
    db_zip_path = os.path.join(
        backup_dir,
        db_zip_filename,
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
            db_zip_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as zf:
            for src_file, arc_name in db_dump_files:
                zf.write(
                    src_file,
                    arcname=arc_name,
                )

    db_zip_size = os.path.getsize(db_zip_path)

    media_root = str(settings.MEDIA_ROOT)
    media_entries: list[tuple[str, str, int]] = []
    if os.path.exists(media_root):
        for root, _, files in os.walk(media_root):
            for fname in sorted(files):
                abs_media_file = os.path.join(
                    root,
                    fname,
                )
                try:
                    fsize = os.path.getsize(abs_media_file)
                except OSError:
                    continue
                if fsize > MAX_ZIP_PART_BYTES:
                    continue
                rel_media_path = os.path.relpath(
                    abs_media_file,
                    media_root,
                )
                media_entries.append((abs_media_file, rel_media_path, fsize))

    chunks: list[list[tuple[str, str, int]]] = []
    current_chunk: list[tuple[str, str, int]] = []
    current_chunk_bytes = 0

    for item in media_entries:
        _, _, fsize = item
        if current_chunk and (current_chunk_bytes + fsize) > MAX_ZIP_PART_BYTES:
            chunks.append(current_chunk)
            current_chunk = [item]
            current_chunk_bytes = fsize
        else:
            current_chunk.append(item)
            current_chunk_bytes += fsize

    if current_chunk:
        chunks.append(current_chunk)

    media_parts: list[dict] = []
    total_parts = len(chunks)

    for idx, chunk in enumerate(chunks, start=1):
        part_filename = (
            f"pomo_media_{ts_label}_part{idx}_of_{total_parts}.zip"
            if total_parts > 1
            else f"pomo_media_{ts_label}.zip"
        )
        part_path = os.path.join(
            backup_dir,
            part_filename,
        )
        with zipfile.ZipFile(
            part_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as mzf:
            for abs_f, rel_f, _ in chunk:
                mzf.write(
                    abs_f,
                    arcname=os.path.join("media", rel_f),
                )
        part_size = os.path.getsize(part_path)
        media_parts.append(
            {
                "part_index": idx,
                "total_parts": total_parts,
                "path": part_path,
                "filename": part_filename,
                "size_bytes": part_size,
                "files_count": len(chunk),
            }
        )

    return {
        "batch_code": batch_code,
        "db_label": db_label,
        "db_zip_path": db_zip_path,
        "db_zip_filename": db_zip_filename,
        "db_zip_size": db_zip_size,
        "total_media_files": len(media_entries),
        "media_parts": media_parts,
    }


async def send_backup_to_admins(
    bot: Bot | None = None,
) -> tuple[bool, str]:
    backup_token = getattr(settings, "BACKUP_BOT_TOKEN", "").strip()
    if not backup_token or "PUT_FULL_BACKUP_BOT_TOKEN_HERE" in backup_token or "FULL_TOKEN_HERE" in backup_token:
        return False, "BACKUP_BOT_TOKEN is not configured."

    async with _BACKUP_LOCK:
        try:
            _, interval_mins, _ = await get_backup_runtime_state()
            archive_info = await create_split_backup_archives_sync()
        except Exception as exc:
            logger.exception(f"Failed to build backup archives: {exc}")
            return False, f"خطا در ساخت فایل‌های بکاپ: {exc}"

        target_ids = set(await get_all_admin_ids())
        admin_username = getattr(settings, "ADMIN_TELEGRAM_USERNAME", "Pomoadmin").lower()

        session = None
        if getattr(settings, "PROXY_URL", ""):
            session = AiohttpSession(proxy=settings.PROXY_URL)

        backup_bot = Bot(
            token=backup_token,
            session=session,
        )
        try:
            try:
                updates = await backup_bot.get_updates(
                    limit=50,
                    timeout=1,
                )
                for upd in updates:
                    msg_obj = upd.message or upd.edited_message
                    if msg_obj and msg_obj.from_user:
                        u_name = (msg_obj.from_user.username or "").lower()
                        if admin_username and u_name == admin_username:
                            target_ids.add(msg_obj.from_user.id)
            except Exception:
                pass

            if not target_ids:
                cleanup_old_backup_files(get_backup_storage_dir())
                return False, "هیچ ادمینی برای ارسال بکاپ یافت نشد."

            rlm = "\u200f"
            now_j = to_jalali_datetime(timezone.now())
            date_str = now_j.strftime("%Y/%m/%d") if now_j else "—"
            time_str = now_j.strftime("%H:%M") if now_j else "—"

            batch_code = archive_info["batch_code"]
            db_label = archive_info["db_label"]
            db_size_str = format_file_size_fa(archive_info["db_zip_size"])
            total_media_files = archive_info["total_media_files"]
            media_parts = archive_info["media_parts"]
            total_parts_count = len(media_parts)

            media_summary_line = (
                f"{total_media_files} فایل (در {total_parts_count} پارت زیپ)"
                if total_parts_count > 0
                else "بدون فایل (خالی)"
            )

            splitter_text = (
                f"{rlm}━━━━━━━━━━━━━━━━━━━━\n"
                f"{rlm}📦 <b>بسته بکاپ خودکار سیستم</b>\n"
                f"{rlm}🆔 کد نوبت: <code>#{batch_code}</code>\n"
                f"{rlm}📅 تاریخ: <b>{date_str}</b> | ساعت: <b>{time_str}</b>\n"
                f"{rlm}💾 دیتابیس: <b>{db_label}</b> ({db_size_str})\n"
                f"{rlm}🖼 پوشه مدیا: <b>{media_summary_line}</b>\n"
                f"{rlm}⏱ دوره بکاپ: <b>هر {interval_mins} دقیقه</b>\n"
                f"{rlm}━━━━━━━━━━━━━━━━━━━━"
            )

            db_caption = (
                f"{rlm}🗄 <b>[دیتابیس] بکاپ کامل اطلاعات</b>\n"
                f"{rlm}🆔 کد نوبت: <code>#{batch_code}</code>\n"
                f"{rlm}💾 موتور: <b>{db_label}</b>\n"
                f"{rlm}📦 حجم فایل: <b>{db_size_str}</b>"
            )

            sent_admins = 0
            for aid in target_ids:
                try:
                    await backup_bot.send_message(
                        chat_id=aid,
                        text=splitter_text,
                        parse_mode="HTML",
                    )
                    await backup_bot.send_document(
                        chat_id=aid,
                        document=FSInputFile(
                            archive_info["db_zip_path"],
                            filename=archive_info["db_zip_filename"],
                        ),
                        caption=db_caption,
                        parse_mode="HTML",
                    )
                    for part in media_parts:
                        p_idx = part["part_index"]
                        p_total = part["total_parts"]
                        p_size_str = format_file_size_fa(part["size_bytes"])
                        p_count = part["files_count"]
                        media_caption = (
                            f"{rlm}🖼 <b>[مدیا] پارت {p_idx} از {p_total}</b>\n"
                            f"{rlm}🆔 کد نوبت: <code>#{batch_code}</code>\n"
                            f"{rlm}📁 تعداد رسید در این پارت: <b>{p_count} فایل</b>\n"
                            f"{rlm}📦 حجم این پارت: <b>{p_size_str}</b>"
                        )
                        await backup_bot.send_document(
                            chat_id=aid,
                            document=FSInputFile(
                                part["path"],
                                filename=part["filename"],
                            ),
                            caption=media_caption,
                            parse_mode="HTML",
                        )
                    sent_admins += 1
                except Exception as exc:
                    logger.warning(f"Failed to send backup batch to admin {aid}: {exc}")

            cleanup_old_backup_files(get_backup_storage_dir())

            if sent_admins > 0:
                await update_backup_runtime_timestamp()
                return True, f"بکاپ #{batch_code} به {sent_admins} ادمین ارسال شد."
            return False, "ارسال بکاپ به ادمین‌ها ناموفق بود (مطمئن شوید ربات بکاپ استارت خورده است)."
        finally:
            await backup_bot.session.close()


async def backup_scheduler_loop(bot: Bot | None = None):
    await asyncio.sleep(10)
    while True:
        try:
            enabled, interval_mins, last_at = await get_backup_runtime_state()
            if enabled:
                now = timezone.now()
                is_due = (
                    last_at is None
                    or (now - last_at) >= timedelta(minutes=interval_mins)
                )
                if is_due:
                    ok, msg = await send_backup_to_admins()
                    if ok:
                        logger.info(f"Backup task: {msg}")
                    else:
                        logger.warning(f"Backup task skipped/failed: {msg}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(f"Backup scheduler loop error: {exc}")

        await asyncio.sleep(30)