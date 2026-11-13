import csv
import io
import json
from collections import defaultdict
from datetime import (
    datetime,
    timedelta,
)
import jdatetime
from django.db.models import (
    Count,
    Max,
    Sum,
    Q,
)
from django.http import HttpResponse
from django.utils import timezone
from core.jalali import (
    format_jalali,
    to_jalali_datetime,
)
from core.models import (
    SubscriptionOrder,
    TelegramUser,
    Transaction,
)

JALALI_MONTH_NAMES = {
    1: "فروردین",
    2: "اردیبهشت",
    3: "خرداد",
    4: "تیر",
    5: "مرداد",
    6: "شهریور",
    7: "مهر",
    8: "آبان",
    9: "آذر",
    10: "دی",
    11: "بهمن",
    12: "اسفند",
}

PERIOD_LABELS = {
    "1d": "۲۴ ساعت گذشته (۱ روز)",
    "3d": "۳ روز گذشته",
    "7d": "۱ هفته گذشته (۷ روز)",
    "30d": "۱ ماه گذشته (۳۰ روز)",
    "90d": "۳ ماه گذشته (۹۰ روز)",
    "365d": "۱ سال گذشته",
    "all": "کل زمان‌ها",
}

SORT_OPTIONS = [
    ("most_spent", "بیشترین مبلغ خرید"),
    ("least_spent", "کمترین مبلغ خرید"),
    ("most_orders", "بیشترین تعداد خرید"),
    ("least_orders", "کمترین تعداد خرید"),
    ("most_deposited", "بیشترین مجموع واریزی"),
    ("highest_wallet", "بیشترین موجودی کیف پول"),
    ("newest", "جدیدترین کاربران"),
]


def fmt_num(val: int | float | None) -> str:
    return f"{int(val or 0):,}"


def to_local_dt(dt):
    if not dt:
        return timezone.localtime(timezone.now())
    if timezone.is_aware(dt):
        return timezone.localtime(dt)
    return timezone.make_aware(dt)


def normalize_digits_and_sep(raw: str) -> str:
    if not raw:
        return ""
    persian_digits = "۰۱۲۳۴۵۶۷۸۹"
    arabic_digits = "٠١٢٣٤٥٦٧٨٩"
    out = str(raw).strip()
    for i in range(10):
        out = out.replace(persian_digits[i], str(i)).replace(arabic_digits[i], str(i))
    return out.replace("-", "/").replace(".", "/")


def parse_jalali_or_gregorian_date(
    raw_str: str | None,
    end_of_day: bool = False,
) -> datetime | None:
    cleaned = normalize_digits_and_sep(raw_str or "")
    if not cleaned:
        return None
    parts = [p for p in cleaned.split("/") if p.isdigit()]
    if len(parts) != 3:
        return None
    y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
    try:
        if 1300 <= y <= 1500:
            g_date = jdatetime.date(y, m, d).togregorian()
        else:
            g_date = datetime(y, m, d).date()

        dt = datetime(
            g_date.year,
            g_date.month,
            g_date.day,
            23 if end_of_day else 0,
            59 if end_of_day else 0,
            59 if end_of_day else 0,
        )
        return timezone.make_aware(dt)
    except Exception:
        return None


def backfill_missing_order_plan_snapshots():
    missing_qs = SubscriptionOrder.objects.filter(
        plan_title="",
        plan__isnull=False,
    ).select_related("plan")
    for order in missing_qs:
        order.plan_title = order.plan.title
        order.plan_category = order.plan.plan_type
        order.save(update_fields=["plan_title", "plan_category"])


def get_jalali_ym_key(dt) -> tuple[int, int]:
    j_dt = to_jalali_datetime(dt) or to_jalali_datetime(timezone.now())
    return j_dt.year, j_dt.month


def format_jalali_ym_label(jy: int, jm: int) -> str:
    m_name = JALALI_MONTH_NAMES.get(jm, str(jm))
    return f"{m_name} {jy}"


def get_last_n_jalali_months(count: int = 12) -> list[tuple[int, int]]:
    j_now = to_jalali_datetime(timezone.now())
    result = []
    curr_y, curr_m = j_now.year, j_now.month
    for _ in range(count):
        result.append((curr_y, curr_m))
        curr_m -= 1
        if curr_m < 1:
            curr_m = 12
            curr_y -= 1
    result.reverse()
    return result


def resolve_period_bounds(
    period_key: str,
    date_from_str: str | None = None,
    date_to_str: str | None = None,
):
    now = timezone.localtime(timezone.now())

    if date_from_str or date_to_str:
        parsed_start = parse_jalali_or_gregorian_date(date_from_str, end_of_day=False)
        parsed_end = parse_jalali_or_gregorian_date(date_to_str, end_of_day=True)
        if parsed_start or parsed_end:
            start_dt = parsed_start or (now - timedelta(days=30))
            end_dt = parsed_end or now
            if start_dt > end_dt:
                start_dt, end_dt = end_dt - timedelta(days=1), start_dt
            s_lbl = format_jalali(start_dt, include_time=False)
            e_lbl = format_jalali(end_dt, include_time=False)
            delta = max(timedelta(hours=1), end_dt - start_dt)
            return (
                start_dt,
                end_dt,
                start_dt - delta,
                start_dt,
                "custom",
                f"بازه انتخابی ({s_lbl} تا {e_lbl})",
            )

    days_map = {
        "1d": 1,
        "3d": 3,
        "7d": 7,
        "30d": 30,
        "90d": 90,
        "365d": 365,
    }
    if period_key == "all":
        first_tx = Transaction.objects.order_by("created_at").first()
        first_ord = SubscriptionOrder.objects.order_by("created_at").first()
        candidates = [
            to_local_dt(x.created_at)
            for x in (first_tx, first_ord)
            if x and x.created_at
        ]
        start_dt = min(candidates) if candidates else (now - timedelta(days=30))
        return start_dt, now, None, None, "all", PERIOD_LABELS["all"]

    days = days_map.get(period_key, 30)
    if period_key not in days_map:
        period_key = "30d"

    start_dt = now - timedelta(days=days)
    prev_end = start_dt
    prev_start = start_dt - timedelta(days=days)
    return (
        start_dt,
        now,
        prev_start,
        prev_end,
        period_key,
        PERIOD_LABELS[period_key],
    )


def calc_growth_percent(current_val: int, prev_val: int | None) -> float | None:
    if prev_val is None:
        return None
    if prev_val == 0:
        return 100.0 if current_val > 0 else 0.0
    return round(((current_val - prev_val) / prev_val) * 100.0, 1)


def build_accounting_context(
    period_key: str = "30d",
    date_from_str: str | None = None,
    date_to_str: str | None = None,
    selected_user_id: str | None = None,
    user_search_query: str | None = None,
    sort_by: str = "most_spent",
) -> dict:
    backfill_missing_order_plan_snapshots()

    start_dt, end_dt, prev_start, prev_end, active_period, period_title = resolve_period_bounds(
        period_key,
        date_from_str,
        date_to_str,
    )

    start_jalali = format_jalali(start_dt, include_time=False)
    end_jalali = format_jalali(end_dt, include_time=False)
    months_12 = get_last_n_jalali_months(12)

    all_users_qs = TelegramUser.objects.all().order_by("-created_at")
    all_users_list = list(all_users_qs)
    total_users_count = len(all_users_list)

    all_users_picker_json = json.dumps(
        [
            {
                "id": u.telegram_id,
                "name": u.full_name or "بدون نام",
                "username": f"@{u.username}" if u.username else "",
                "balance": fmt_num(u.wallet_balance),
            }
            for u in all_users_list
        ],
        ensure_ascii=False,
    )

    selected_user_analytics = None
    resolved_uid = None
    if selected_user_id and str(selected_user_id).strip().lstrip("-").isdigit():
        resolved_uid = int(str(selected_user_id).strip())
        target_user = TelegramUser.objects.filter(telegram_id=resolved_uid).first()
        if target_user:
            selected_user_analytics = build_single_user_analytics(
                target_user,
                months_12,
            )

    tx_in_period = Transaction.objects.filter(
        created_at__gte=start_dt,
        created_at__lte=end_dt,
    )
    approved_tx_qs = tx_in_period.filter(status="approved")
    orders_in_period = SubscriptionOrder.objects.filter(
        created_at__gte=start_dt,
        created_at__lte=end_dt,
    )
    paid_orders_qs = orders_in_period.filter(order_type="purchase").select_related("plan")

    deposit_total = approved_tx_qs.aggregate(s=Sum("amount"))["s"] or 0
    deposit_count = approved_tx_qs.count()
    sales_total = paid_orders_qs.aggregate(s=Sum("price_paid"))["s"] or 0
    sales_count = paid_orders_qs.count()

    prev_deposit_total = None
    prev_sales_total = None
    if prev_start and prev_end:
        prev_deposit_total = (
            Transaction.objects.filter(
                status="approved",
                created_at__gte=prev_start,
                created_at__lt=prev_end,
            ).aggregate(s=Sum("amount"))["s"]
            or 0
        )
        prev_sales_total = (
            SubscriptionOrder.objects.filter(
                order_type="purchase",
                created_at__gte=prev_start,
                created_at__lt=prev_end,
            ).aggregate(s=Sum("price_paid"))["s"]
            or 0
        )

    deposit_growth = calc_growth_percent(deposit_total, prev_deposit_total)
    sales_growth = calc_growth_percent(sales_total, prev_sales_total)

    total_wallet_liability = sum(u.wallet_balance for u in all_users_list)
    active_subs_count = SubscriptionOrder.objects.filter(status="active").count()

    trend_points = []
    local_start = to_local_dt(start_dt)
    local_end = to_local_dt(end_dt)
    span_hours = max(1.0, (local_end - local_start).total_seconds() / 3600.0)

    approved_tx_list = list(approved_tx_qs.values("amount", "created_at"))
    paid_orders_list = list(paid_orders_qs.values("price_paid", "created_at"))

    if span_hours <= 36 and active_period != "all":
        bucket_deposits = defaultdict(int)
        bucket_sales = defaultdict(int)

        hours_count = int(span_hours) + 1
        base_hour = local_start.replace(minute=0, second=0, microsecond=0)
        hour_keys = [
            base_hour + timedelta(hours=i)
            for i in range(hours_count + 1)
        ]

        for item in approved_tx_list:
            ldt = to_local_dt(item["created_at"]).replace(minute=0, second=0, microsecond=0)
            bucket_deposits[ldt] += item["amount"]

        for item in paid_orders_list:
            ldt = to_local_dt(item["created_at"]).replace(minute=0, second=0, microsecond=0)
            bucket_sales[ldt] += item["price_paid"]

        for h_dt in hour_keys:
            if h_dt > local_end + timedelta(hours=1):
                continue
            label = h_dt.strftime("%H:00")
            trend_points.append(
                {
                    "label": label,
                    "deposit": bucket_deposits[h_dt],
                    "sales": bucket_sales[h_dt],
                }
            )
    else:
        raw_days = int((local_end.date() - local_start.date()).days) + 1
        min_days = 7 if active_period == "all" else 1
        total_days = min(90, max(min_days, raw_days))
        plot_start_date = local_end.date() - timedelta(days=total_days - 1)

        day_deposits = defaultdict(int)
        day_sales = defaultdict(int)

        for item in approved_tx_list:
            d_key = to_local_dt(item["created_at"]).date()
            day_deposits[d_key] += item["amount"]

        for item in paid_orders_list:
            d_key = to_local_dt(item["created_at"]).date()
            day_sales[d_key] += item["price_paid"]

        for i in range(total_days):
            curr_date = plot_start_date + timedelta(days=i)
            j_date = jdatetime.date.fromgregorian(date=curr_date)
            jm, jd = j_date.month, j_date.day
            trend_points.append(
                {
                    "label": f"{jm:02d}/{jd:02d}",
                    "deposit": day_deposits[curr_date],
                    "sales": day_sales[curr_date],
                }
            )

    monthly_deposits = defaultdict(int)
    monthly_sales = defaultdict(int)

    one_year_ago = timezone.now() - timedelta(days=380)
    for item in Transaction.objects.filter(
        status="approved",
        created_at__gte=one_year_ago,
    ).values("amount", "created_at"):
        ym = get_jalali_ym_key(item["created_at"])
        monthly_deposits[ym] += item["amount"]

    for item in SubscriptionOrder.objects.filter(
        order_type="purchase",
        created_at__gte=one_year_ago,
    ).values("price_paid", "created_at"):
        ym = get_jalali_ym_key(item["created_at"])
        monthly_sales[ym] += item["price_paid"]

    monthly_chart = []
    non_zero_months = [
        monthly_deposits[ym]
        for ym in months_12
        if monthly_deposits[ym] > 0
    ]
    avg_monthly_val = (
        sum(non_zero_months) / len(non_zero_months)
        if non_zero_months
        else 0
    )

    for jy, jm in months_12:
        dep_val = monthly_deposits[(jy, jm)]
        sal_val = monthly_sales[(jy, jm)]
        if dep_val == 0 and sal_val == 0:
            bar_color = "#374151"
        elif dep_val >= avg_monthly_val * 1.15:
            bar_color = "#22c55e"
        elif dep_val <= avg_monthly_val * 0.65:
            bar_color = "#f59e0b"
        else:
            bar_color = "#a855f7"

        monthly_chart.append(
            {
                "label": format_jalali_ym_label(jy, jm),
                "short_label": JALALI_MONTH_NAMES.get(jm, str(jm)),
                "deposit": dep_val,
                "sales": sal_val,
                "bar_color": bar_color,
            }
        )

    plan_agg = defaultdict(lambda: {"count": 0, "revenue": 0, "category": "direct"})
    direct_rev = 0
    direct_cnt = 0
    tunnel_rev = 0
    tunnel_cnt = 0

    for o in paid_orders_qs:
        p_title = (o.plan_title or (o.plan.title if o.plan else "")).strip() or "پلن متفرقه"
        p_cat = (o.plan_category or (o.plan.plan_type if o.plan else "direct")).strip()
        plan_agg[p_title]["count"] += 1
        plan_agg[p_title]["revenue"] += o.price_paid
        plan_agg[p_title]["category"] = p_cat

        if p_cat == "tunnel":
            tunnel_rev += o.price_paid
            tunnel_cnt += 1
        else:
            direct_rev += o.price_paid
            direct_cnt += 1

    plan_breakdown = [
        {
            "title": title_str,
            "sold_count": info["count"],
            "revenue": info["revenue"],
            "revenue_fmt": fmt_num(info["revenue"]),
            "category": info["category"],
        }
        for title_str, info in sorted(
            plan_agg.items(),
            key=lambda item: (item[1]["count"], item[1]["revenue"]),
            reverse=True,
        )[:8]
    ]

    cat_total_rev = max(1, direct_rev + tunnel_rev)
    direct_share_pct = round((direct_rev / cat_total_rev) * 100, 1) if (direct_rev + tunnel_rev) > 0 else 0
    tunnel_share_pct = round(100.0 - direct_share_pct, 1) if (direct_rev + tunnel_rev) > 0 else 0

    all_time_orders_map = {
        row["user_id"]: row
        for row in SubscriptionOrder.objects.filter(order_type="purchase")
        .values("user_id")
        .annotate(
            cnt=Count("id"),
            spent=Sum("price_paid"),
            last_at=Max("created_at"),
        )
    }
    period_orders_map = {
        row["user_id"]: row
        for row in paid_orders_qs.values("user_id").annotate(
            cnt=Count("id"),
            spent=Sum("price_paid"),
        )
    }
    all_time_tx_map = {
        row["user_id"]: row
        for row in Transaction.objects.filter(status="approved")
        .values("user_id")
        .annotate(
            cnt=Count("id"),
            deposited=Sum("amount"),
        )
    }

    q_clean = (user_search_query or "").strip().lstrip("@").lower()
    users_financial_rows = []
    for u in all_users_list:
        if q_clean:
            haystack = f"{u.telegram_id} {u.full_name or ''} {u.username or ''}".lower()
            if q_clean not in haystack:
                continue

        o_all = all_time_orders_map.get(u.telegram_id, {})
        o_per = period_orders_map.get(u.telegram_id, {})
        t_all = all_time_tx_map.get(u.telegram_id, {})

        total_spent_u = int(o_all.get("spent") or 0)
        total_cnt_u = int(o_all.get("cnt") or 0)
        period_spent_u = int(o_per.get("spent") or 0)
        period_cnt_u = int(o_per.get("cnt") or 0)
        total_dep_u = int(t_all.get("deposited") or 0)
        last_at_u = o_all.get("last_at")

        users_financial_rows.append(
            {
                "telegram_id": u.telegram_id,
                "full_name": u.full_name or "بدون نام",
                "username": f"@{u.username}" if u.username else "—",
                "wallet_balance": u.wallet_balance,
                "wallet_balance_fmt": fmt_num(u.wallet_balance),
                "period_spent": period_spent_u,
                "period_spent_fmt": fmt_num(period_spent_u),
                "period_cnt": period_cnt_u,
                "total_spent": total_spent_u,
                "total_spent_fmt": fmt_num(total_spent_u),
                "total_cnt": total_cnt_u,
                "total_deposited": total_dep_u,
                "total_deposited_fmt": fmt_num(total_dep_u),
                "last_purchase_jalali": format_jalali(last_at_u, include_time=False) if last_at_u else "—",
                "created_at": u.created_at,
            }
        )

    valid_sorts = {k for k, _ in SORT_OPTIONS}
    if sort_by not in valid_sorts:
        sort_by = "most_spent"

    if sort_by == "most_spent":
        users_financial_rows.sort(key=lambda r: (r["period_spent"], r["total_spent"], r["total_deposited"]), reverse=True)
    elif sort_by == "least_spent":
        users_financial_rows.sort(key=lambda r: (r["period_spent"], r["total_spent"], r["total_deposited"]))
    elif sort_by == "most_orders":
        users_financial_rows.sort(key=lambda r: (r["period_cnt"], r["total_cnt"], r["total_spent"]), reverse=True)
    elif sort_by == "least_orders":
        users_financial_rows.sort(key=lambda r: (r["period_cnt"], r["total_cnt"], r["total_spent"]))
    elif sort_by == "most_deposited":
        users_financial_rows.sort(key=lambda r: (r["total_deposited"], r["total_spent"]), reverse=True)
    elif sort_by == "highest_wallet":
        users_financial_rows.sort(key=lambda r: (r["wallet_balance"], r["total_spent"]), reverse=True)
    elif sort_by == "newest":
        users_financial_rows.sort(key=lambda r: r["created_at"], reverse=True)

    trend_chart_json = json.dumps(
        {
            "labels": [p["label"] for p in trend_points],
            "deposits": [p["deposit"] for p in trend_points],
            "sales": [p["sales"] for p in trend_points],
        }
    )
    monthly_chart_json = json.dumps(
        {
            "labels": [m["short_label"] for m in monthly_chart],
            "deposits": [m["deposit"] for m in monthly_chart],
            "sales": [m["sales"] for m in monthly_chart],
            "colors": [m["bar_color"] for m in monthly_chart],
        }
    )
    plans_chart_json = json.dumps(
        {
            "labels": [p["title"] for p in plan_breakdown],
            "counts": [p["sold_count"] for p in plan_breakdown],
            "revenues": [p["revenue"] for p in plan_breakdown],
            "colors": [
                "#3b82f6" if p["category"] == "tunnel" else "#22c55e"
                for p in plan_breakdown
            ],
        }
    )

    return {
        "active_period": active_period,
        "period_title": period_title,
        "date_from_jalali": date_from_str or start_jalali,
        "date_to_jalali": date_to_str or end_jalali,
        "start_jalali": start_jalali,
        "end_jalali": end_jalali,
        "deposit_total": deposit_total,
        "deposit_total_fmt": fmt_num(deposit_total),
        "deposit_count": deposit_count,
        "deposit_growth": deposit_growth,
        "sales_total": sales_total,
        "sales_total_fmt": fmt_num(sales_total),
        "sales_count": sales_count,
        "sales_growth": sales_growth,
        "total_wallet_liability": total_wallet_liability,
        "total_wallet_liability_fmt": fmt_num(total_wallet_liability),
        "active_subs_count": active_subs_count,
        "total_users_count": total_users_count,
        "monthly_chart": monthly_chart,
        "direct_rev": direct_rev,
        "direct_rev_fmt": fmt_num(direct_rev),
        "direct_cnt": direct_cnt,
        "direct_share_pct": direct_share_pct,
        "tunnel_rev": tunnel_rev,
        "tunnel_rev_fmt": fmt_num(tunnel_rev),
        "tunnel_cnt": tunnel_cnt,
        "tunnel_share_pct": tunnel_share_pct,
        "plan_breakdown": plan_breakdown,
        "users_financial_rows": users_financial_rows,
        "sort_options": SORT_OPTIONS,
        "active_sort": sort_by,
        "all_users_picker_json": all_users_picker_json,
        "selected_user_id": resolved_uid,
        "user_search_query": user_search_query or "",
        "user_analytics": selected_user_analytics,
        "trend_chart_json": trend_chart_json,
        "monthly_chart_json": monthly_chart_json,
        "plans_chart_json": plans_chart_json,
    }


def build_single_user_analytics(
    user: TelegramUser,
    months_12: list[tuple[int, int]],
) -> dict:
    user_txs = list(
        Transaction.objects.filter(user=user).order_by("-created_at")
    )
    user_orders = list(
        SubscriptionOrder.objects.filter(user=user)
        .select_related("plan")
        .order_by("-created_at")
    )

    approved_txs = [tx for tx in user_txs if tx.status == "approved"]
    paid_orders = [o for o in user_orders if o.order_type == "purchase"]

    total_deposited = sum(tx.amount for tx in approved_txs)
    total_spent_orders = sum(o.price_paid for o in paid_orders)
    purchase_count = len(paid_orders)

    u_month_spent = defaultdict(int)
    u_plan_agg = defaultdict(lambda: {"count": 0, "spent": 0})

    for o in paid_orders:
        ym = get_jalali_ym_key(o.created_at)
        u_month_spent[ym] += o.price_paid
        p_title = (o.plan_title or (o.plan.title if o.plan else "")).strip() or "پلن متفرقه"
        u_plan_agg[p_title]["count"] += 1
        u_plan_agg[p_title]["spent"] += o.price_paid

    avg_purchase = int(total_spent_orders / purchase_count) if purchase_count > 0 else 0
    last_purchase_jalali = (
        format_jalali(paid_orders[0].created_at, include_time=False)
        if paid_orders
        else "ندارد"
    )

    active_months_count = sum(1 for ym in months_12 if u_month_spent[ym] > 0)
    zero_months_count = 12 - active_months_count

    user_monthly_series = []
    best_month_label = "—"
    best_month_val = 0
    low_months_labels = []

    for jy, jm in months_12:
        sp_val = u_month_spent[(jy, jm)]
        lbl = format_jalali_ym_label(jy, jm)

        if sp_val > best_month_val:
            best_month_val = sp_val
            best_month_label = lbl

        if sp_val == 0:
            bar_color = "#374151"
            low_months_labels.append(JALALI_MONTH_NAMES.get(jm, str(jm)))
        elif sp_val < avg_purchase:
            bar_color = "#f59e0b"
        else:
            bar_color = "#22c55e"

        user_monthly_series.append(
            {
                "label": lbl,
                "short_label": JALALI_MONTH_NAMES.get(jm, str(jm)),
                "spent": sp_val,
                "bar_color": bar_color,
            }
        )

    favorite_plans = [
        {
            "title": k,
            "count": v["count"],
            "spent_fmt": fmt_num(v["spent"]),
        }
        for k, v in sorted(
            u_plan_agg.items(),
            key=lambda item: (item[1]["count"], item[1]["spent"]),
            reverse=True,
        )
    ]

    user_chart_json = json.dumps(
        {
            "labels": [m["short_label"] for m in user_monthly_series],
            "spent": [m["spent"] for m in user_monthly_series],
            "colors": [m["bar_color"] for m in user_monthly_series],
        }
    )

    return {
        "user": user,
        "wallet_balance_fmt": fmt_num(user.wallet_balance),
        "joined_jalali": format_jalali(user.created_at, include_time=False),
        "total_deposited_fmt": fmt_num(total_deposited),
        "total_spent_orders_fmt": fmt_num(total_spent_orders),
        "purchase_count": purchase_count,
        "best_month_label": best_month_label,
        "best_month_val_fmt": fmt_num(best_month_val),
        "zero_months_count": zero_months_count,
        "last_purchase_jalali": last_purchase_jalali,
        "low_months_summary": "، ".join(low_months_labels) if low_months_labels else "همه ماه‌ها فعال",
        "favorite_plans": favorite_plans,
        "user_chart_json": user_chart_json,
        "recent_orders": [
            {
                "custom_name": o.custom_name,
                "plan_title": o.plan_title or (o.plan.title if o.plan else o.get_order_type_display()),
                "price_paid_fmt": fmt_num(o.price_paid),
                "created_jalali": format_jalali(o.created_at),
            }
            for o in user_orders[:10]
        ],
    }


def export_accounting_excel_response(
    period_key: str = "30d",
    date_from_str: str | None = None,
    date_to_str: str | None = None,
    selected_user_id: str | None = None,
) -> HttpResponse:
    ctx = build_accounting_context(
        period_key=period_key,
        date_from_str=date_from_str,
        date_to_str=date_to_str,
        selected_user_id=selected_user_id,
    )
    start_dt, end_dt, _, _, _, _ = resolve_period_bounds(
        period_key,
        date_from_str,
        date_to_str,
    )

    tx_qs = (
        Transaction.objects.filter(
            created_at__gte=start_dt,
            created_at__lte=end_dt,
        )
        .select_related("user", "target_plan")
        .order_by("-created_at")
    )
    orders_qs = (
        SubscriptionOrder.objects.filter(
            created_at__gte=start_dt,
            created_at__lte=end_dt,
        )
        .select_related("user", "plan")
        .order_by("-created_at")
    )

    if selected_user_id and str(selected_user_id).isdigit():
        tx_qs = tx_qs.filter(user__telegram_id=int(selected_user_id))
        orders_qs = orders_qs.filter(user__telegram_id=int(selected_user_id))

    filename_base = f"accounting_report_{period_key}_{timezone.now().strftime('%Y%m%d_%H%M')}"

    try:
        import openpyxl
        from openpyxl.styles import (
            Font,
            PatternFill,
        )

        wb = openpyxl.Workbook()

        ws_summary = wb.active
        ws_summary.title = "خلاصه و آمار پلن‌ها"
        ws_summary.views.sheetView[0].rightToLeft = True

        header_fill = PatternFill(
            start_color="1E293B",
            end_color="1E293B",
            fill_type="solid",
        )
        header_font = Font(
            bold=True,
            color="FFFFFF",
        )

        summary_rows = [
            ["شاخص مالی", "مقدار"],
            ["عنوان بازه گزارش", ctx["period_title"]],
            ["از تاریخ (شمسی)", ctx["start_jalali"]],
            ["تا تاریخ (شمسی)", ctx["end_jalali"]],
            ["مجموع واریزی تایید شده (تومان)", ctx["deposit_total"]],
            ["تعداد فیش‌های تایید شده", ctx["deposit_count"]],
            ["مجموع فروش اشتراک‌ها (تومان)", ctx["sales_total"]],
            ["تعداد اشتراک‌های فروخته شده", ctx["sales_count"]],
            ["مجموع موجودی کیف پول کاربران (تومان)", ctx["total_wallet_liability"]],
        ]

        for r_idx, row in enumerate(summary_rows, start=1):
            ws_summary.append(row)
            if r_idx == 1:
                for col_idx in range(1, 3):
                    cell = ws_summary.cell(row=r_idx, column=col_idx)
                    cell.fill = header_fill
                    cell.font = header_font

        ws_summary.append([])
        ws_summary.append(["عنوان پلن (ثبت‌شده در زمان خرید)", "تعداد فروش", "مجموع درآمد (تومان)"])
        for pb in ctx["plan_breakdown"]:
            ws_summary.append([pb["title"], pb["sold_count"], pb["revenue"]])

        ws_users = wb.create_sheet(title="عملکرد مالی کاربران")
        ws_users.views.sheetView[0].rightToLeft = True
        u_headers = [
            "آیدی تلگرام",
            "نام کامل",
            "یوزرنیم",
            "خرید در بازه (تومان)",
            "تعداد خرید در بازه",
            "کل خرید (تومان)",
            "کل واریزی تایید شده (تومان)",
            "موجودی فعلی کیف پول (تومان)",
        ]
        ws_users.append(u_headers)
        for col_idx in range(1, len(u_headers) + 1):
            cell = ws_users.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font

        for ur in ctx["users_financial_rows"]:
            ws_users.append(
                [
                    ur["telegram_id"],
                    ur["full_name"],
                    ur["username"],
                    ur["period_spent"],
                    ur["period_cnt"],
                    ur["total_spent"],
                    ur["total_deposited"],
                    ur["wallet_balance"],
                ]
            )

        ws_ord = wb.create_sheet(title="ریز سفارش‌ها")
        ws_ord.views.sheetView[0].rightToLeft = True
        ord_headers = [
            "شناسه سفارش",
            "آیدی تلگرام",
            "نام کاربر",
            "نام سرویس",
            "عنوان پلن در زمان خرید",
            "مبلغ پرداختی (تومان)",
            "وضعیت",
            "تاریخ ثبت (شمسی)",
        ]
        ws_ord.append(ord_headers)
        for col_idx in range(1, len(ord_headers) + 1):
            cell = ws_ord.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font

        for o in orders_qs[:2000]:
            ws_ord.append(
                [
                    o.id,
                    o.user.telegram_id,
                    o.user.full_name or "",
                    o.custom_name,
                    o.plan_title or (o.plan.title if o.plan else o.get_order_type_display()),
                    o.price_paid,
                    o.get_status_display(),
                    format_jalali(o.created_at),
                ]
            )

        ws_tx = wb.create_sheet(title="ریز واریزی‌ها")
        ws_tx.views.sheetView[0].rightToLeft = True
        tx_headers = [
            "شماره فاکتور",
            "آیدی تلگرام",
            "نام کاربر",
            "مبلغ (تومان)",
            "وضعیت",
            "تاریخ ثبت (شمسی)",
        ]
        ws_tx.append(tx_headers)
        for col_idx in range(1, len(tx_headers) + 1):
            cell = ws_tx.cell(row=1, column=col_idx)
            cell.fill = header_fill
            cell.font = header_font

        for tx in tx_qs[:2000]:
            ws_tx.append(
                [
                    tx.invoice_number,
                    tx.user.telegram_id,
                    tx.user.full_name or "",
                    tx.amount,
                    tx.get_status_display(),
                    format_jalali(tx.created_at),
                ]
            )

        for sheet in wb.worksheets:
            for col in sheet.columns:
                max_len = max(len(str(cell.value or "")) for cell in col)
                col_letter = col[0].column_letter
                sheet.column_dimensions[col_letter].width = min(max(max_len + 4, 14), 45)

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        response = HttpResponse(
            buffer.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename_base}.xlsx"'
        return response

    except ImportError:
        response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
        response["Content-Disposition"] = f'attachment; filename="{filename_base}.csv"'
        writer = csv.writer(response)
        writer.writerow(["گزارش مالی ربات", ctx["period_title"], f"از {ctx['start_jalali']} تا {ctx['end_jalali']}"])
        writer.writerow(["مجموع واریزی تایید شده (تومان)", ctx["deposit_total"], "مجموع فروش سرویس (تومان)", ctx["sales_total"]])
        return response