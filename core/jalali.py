from datetime import datetime
import jdatetime
from django.utils import timezone


def to_jalali_datetime(
    dt: datetime | None,
) -> jdatetime.datetime | None:
    if not dt:
        return None
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return jdatetime.datetime.fromgregorian(datetime=dt)


def format_jalali(
    dt: datetime | None,
    include_time: bool = True,
) -> str:
    j_dt = to_jalali_datetime(dt)
    if not j_dt:
        return "—"
    if include_time:
        return j_dt.strftime("%Y/%m/%d - %H:%M")
    return j_dt.strftime("%Y/%m/%d")


def now_jalali_str(
    include_time: bool = True,
) -> str:
    return format_jalali(
        timezone.now(),
        include_time=include_time,
    )


def get_current_jalali_year_month() -> tuple[str, str]:
    j_now = to_jalali_datetime(timezone.now())
    return (
        j_now.strftime("%Y"),
        j_now.strftime("%m"),
    )