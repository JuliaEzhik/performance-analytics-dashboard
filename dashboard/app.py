import os
from calendar import month_abbr
from datetime import timedelta
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from components import (
    apply_styles,
    render_banner,
    render_data_quality_panel,
    render_hero,
    render_insights,
    render_metric_cards,
)
from i18n import t

DB_PATH = os.getenv(
    "WAREHOUSE_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "warehouse.duckdb"),
)
DEFAULT_SCHEMA = "gold"

PRIMARY = "#2E7D5B"
ACCENT = "#E0A526"
CHANNEL_COLORS = {
    "Organic Search": "#2E7D5B",
    "Organic Social": "#5DA9E9",
    "AI Assistant": "#E0A526",
    "Direct": "#8E7CC3",
    "Referral": "#A0A0A0",
    "Email": "#4DB6AC",
    "Offline": "#25D366",
    "Paid Display": "#E4572E",
    "Paid Video": "#F28E79",
    "Paid Search": "#B23A1E",
    "Paid Other": "#F5B7A8",
    "Spam Referral": "#5A5A5A",
    "Display": "#C77D5B",
    "Unassigned": "#CCCCCC",
}

st.set_page_config(
    page_title="Performance Analysis Dashboard",
    page_icon="📊",
    layout="wide",
)
apply_styles()


# ---------------------------------------------------------------- data

@st.cache_data(ttl=3600, show_spinner=True)
def load_table(table: str, schema: str | None = None) -> pd.DataFrame:
    """Read one table from the local DuckDB warehouse built by dbt."""
    if not Path(DB_PATH).exists():
        st.error(
            f"Warehouse not found at `{DB_PATH}`. Run `make data` (generate + dbt build) first."
        )
        st.stop()
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        df = con.execute(f"select * from {schema or DEFAULT_SCHEMA}.{table}").df()
    finally:
        con.close()
    for col in df.columns:
        if col.endswith(("_date", "_week", "_month")):
            df[col] = pd.to_datetime(df[col])
    return df


def format_money(value: float | None) -> str:
    if value is None or pd.isna(value):
        return "—"
    if value >= 1_000_000:
        return f"€{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"€{value / 1_000:.1f}K"
    return f"€{value:,.0f}"


def marketing_summary(sessions: pd.DataFrame, successful: pd.DataFrame, cpc_map: dict) -> dict:
    leads = int(sessions["reached_booking_opened"].sum()) if not sessions.empty else 0
    revenue = float(successful["estimated_revenue"].fillna(0).sum()) if not successful.empty else 0.0
    cost = float(sessions["channel_group"].map(cpc_map).fillna(0).sum()) if not sessions.empty else 0.0
    # ROAS must use only bookings attributed to paid channels — not organic / offline revenue.
    if successful.empty or "channel_group" not in successful.columns:
        paid_revenue = 0.0
    else:
        paid_mask = successful["channel_group"].fillna("").isin(cpc_map.keys())
        paid_revenue = float(successful.loc[paid_mask, "estimated_revenue"].fillna(0).sum())
    return {
        "leads": leads,
        "revenue": revenue,
        "cost": cost,
        "paid_revenue": paid_revenue,
        "roas": (paid_revenue / cost) if cost else None,
        "cpl": (cost / leads) if leads else None,
    }


def summarize(s: pd.DataFrame) -> dict | None:
    if s.empty:
        return None
    return {
        "users": s["user_pseudo_id"].nunique(),
        "sessions": len(s),
        "engagement_rate": s["is_engaged"].mean(),
        "avg_engagement_sec": s["engagement_time_sec"].mean(),
        "booking_open_rate": s["reached_booking_opened"].mean(),
        "submit_rate": s["reached_booking_submit"].mean(),
        "submit_sessions": int(s["reached_booking_submit"].sum()),
        "bookings": int(s["bookings"].sum()),
    }


def group_metrics(s: pd.DataFrame, by: str) -> pd.DataFrame:
    out = (
        s.groupby(by, dropna=False)
        .agg(
            sessions=("session_key", "size"),
            users=("user_pseudo_id", "nunique"),
            engagement_rate=("is_engaged", "mean"),
            avg_engagement_sec=("engagement_time_sec", "mean"),
            pages_per_session=("page_views", "mean"),
            booking_open_rate=("reached_booking_opened", "mean"),
            submit_sessions=("reached_booking_submit", "sum"),
            submit_rate=("reached_booking_submit", "mean"),
            bookings=("bookings", "sum"),
        )
        .reset_index()
        .sort_values("sessions", ascending=False)
    )
    for col in ["engagement_rate", "booking_open_rate", "submit_rate"]:
        out[col] = out[col].astype(float) * 100
    return out


def fmt_duration(seconds: float | None) -> str:
    if seconds is None or pd.isna(seconds):
        return "–"
    minutes, secs = divmod(int(round(seconds)), 60)
    return f"{minutes}m {secs:02d}s" if minutes else f"{secs}s"


def pct_change(cur, prev) -> str | None:
    if prev is None or not prev:
        return None
    return f"{(cur - prev) / prev:+.0%}"


def rate_columns(lang: str) -> dict:
    return {
        "engagement_rate": st.column_config.NumberColumn(t(lang, "col_engagement_rate"), format="%.1f%%"),
        "booking_open_rate": st.column_config.NumberColumn(t(lang, "col_opened_booking"), format="%.1f%%"),
        "submit_rate": st.column_config.NumberColumn(t(lang, "col_submit_rate"), format="%.1f%%"),
        "avg_engagement_sec": st.column_config.NumberColumn(t(lang, "col_avg_engagement"), format="%.0f"),
        "pages_per_session": st.column_config.NumberColumn(t(lang, "col_pages_per_session"), format="%.2f"),
        "submit_sessions": st.column_config.NumberColumn(t(lang, "col_submit_sessions")),
        "sessions": st.column_config.NumberColumn(t(lang, "col_sessions")),
        "users": st.column_config.NumberColumn(t(lang, "col_users")),
        "bookings": st.column_config.NumberColumn(t(lang, "col_bookings")),
    }


def show_table(df: pd.DataFrame, lang: str, **kwargs):
    st.dataframe(df, hide_index=True, width="stretch", column_config=rate_columns(lang), **kwargs)


# ---------------------------------------------------------------- load

sessions_all = load_table("gold_fct_sessions")
bookings_all = load_table("gold_fct_bookings")
daily_kpis = load_table("gold_agg_daily_kpis")
pages = load_table("gold_agg_page_performance")
destinations = load_table("gold_agg_destination_demand")
dq_df = load_table("gold_agg_data_quality")
spam_referrers = load_table("spam_referrers", schema="silver")
cpc_df = load_table("silver_channel_cpc", schema="silver")
cpc_map = dict(zip(cpc_df["channel_group"], cpc_df["cpc"].astype(float)))
spam_reason_map = {
    str(domain).lower(): reason
    for domain, reason in zip(spam_referrers["referrer_domain"], spam_referrers["reason"])
}


def spam_reason_for(source) -> str:
    if source is None or (isinstance(source, float) and pd.isna(source)):
        return "matched spam_referrers list"
    src = str(source).lower()
    for domain, reason in spam_reason_map.items():
        if src == domain or src.endswith("." + domain) or src.endswith(domain):
            return str(reason)
    return "matched spam_referrers list"

data_start = min(sessions_all["session_date"].min(), bookings_all["booked_date"].min()).date()
data_end = max(sessions_all["session_date"].max(), bookings_all["booked_date"].max()).date()

DE_MONTH_ABBR = {
    1: "Jan", 2: "Feb", 3: "Mär", 4: "Apr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Dez",
}


def month_label(period: pd.Period, lang_code: str) -> str:
    if lang_code == "de":
        return f"{DE_MONTH_ABBR[period.month]} {period.year}"
    return f"{month_abbr[period.month]} {period.year}"


available_months = sorted(
    {
        *sessions_all["session_date"].dt.to_period("M").unique().tolist(),
        *bookings_all["booked_date"].dt.to_period("M").unique().tolist(),
    }
)


# ---------------------------------------------------------------- sidebar: language + filters

with st.sidebar:
    lang_choice = st.radio(
        "Language / Sprache",
        ["English", "Deutsch"],
        horizontal=True,
        key="lang_choice",
    )
    lang = "de" if lang_choice == "Deutsch" else "en"

    st.markdown(f"### {t(lang, 'filters')}")

    month_options = {month_label(p, lang): p for p in available_months}
    picked_month_labels = st.multiselect(
        t(lang, "month"),
        options=list(month_options),
        default=list(month_options),
        help=t(lang, "month_help"),
        placeholder=t(lang, "all_months"),
        key="month_filter",
    )
    picked_months = [month_options[label] for label in picked_month_labels] or available_months
    picked_months = sorted(picked_months)

    month_start = max(data_start, picked_months[0].to_timestamp().date())
    month_end = min(
        data_end,
        (picked_months[-1] + 1).to_timestamp().date() - timedelta(days=1),
    )

    # When months change, reset the date range to the selected months' span.
    month_sig = tuple(str(p) for p in picked_months)
    if st.session_state.get("_month_sig") != month_sig:
        st.session_state["date_range_input"] = (month_start, month_end)
        st.session_state["_month_sig"] = month_sig

    picked = st.date_input(
        t(lang, "date_range"),
        min_value=data_start,
        max_value=data_end,
        help=t(lang, "date_help", start=f"{data_start:%d %b %Y}"),
        key="date_range_input",
    )
    start, end = (picked if isinstance(picked, tuple) and len(picked) == 2 else (month_start, month_end))
    start = max(start, month_start)
    end = min(end, month_end)
    if start > end:
        start, end = month_start, month_end

    channels = sorted(sessions_all["channel_group"].unique())
    picked_channels = st.multiselect(t(lang, "channel"), channels, default=channels)
    devices = sorted(sessions_all["device_category"].unique())
    picked_devices = st.multiselect(t(lang, "device"), devices, default=devices)
    countries = sessions_all["country"].value_counts().index.tolist()
    picked_countries = st.multiselect(t(lang, "country"), countries, placeholder=t(lang, "all_countries"))
    exclude_spam = st.checkbox(
        t(lang, "exclude_spam"),
        value=False,
        help=t(lang, "exclude_spam_help"),
    )
    st.caption(t(lang, "internal_caption"))


def _in_picked_months(series: pd.Series) -> pd.Series:
    return series.dt.to_period("M").isin(picked_months)


def apply_filters(
    df: pd.DataFrame,
    date_from,
    date_to,
    *,
    respect_months: bool = True,
) -> pd.DataFrame:
    mask = (
        df["session_date"].between(pd.Timestamp(date_from), pd.Timestamp(date_to))
        & df["channel_group"].isin(picked_channels)
        & df["device_category"].isin(picked_devices)
    )
    if respect_months:
        mask &= _in_picked_months(df["session_date"])
    if picked_countries:
        mask &= df["country"].isin(picked_countries)
    if exclude_spam:
        mask &= ~df["is_spam_referrer"].astype(bool)
    return df[mask]


sessions = apply_filters(sessions_all, start, end)
period_days = (end - start).days + 1
prev_end = start - timedelta(days=1)
prev_start = prev_end - timedelta(days=period_days - 1)
# Previous period keeps channel/device filters but ignores the month picker
# so month-to-month deltas still work when a single month is selected.
sessions_prev = apply_filters(sessions_all, prev_start, prev_end, respect_months=False)

bookings = bookings_all[
    bookings_all["booked_date"].between(pd.Timestamp(start), pd.Timestamp(end))
    & _in_picked_months(bookings_all["booked_date"])
].copy()
external_bookings = bookings[~bookings["is_internal_booking"].astype(bool)]
successful = external_bookings[external_bookings["is_successful"].astype(bool)]


# ---------------------------------------------------------------- header

current = summarize(sessions)
previous = summarize(sessions_prev)

prev_bookings = bookings_all[bookings_all["booked_date"].between(pd.Timestamp(prev_start), pd.Timestamp(prev_end))]
prev_bookings = prev_bookings[~prev_bookings["is_internal_booking"].astype(bool)]
prev_successful = prev_bookings[prev_bookings["is_successful"].astype(bool)]
backend_n = int(len(external_bookings))
successful_n = int(len(successful))
prev_backend_n = int(len(prev_bookings))
prev_successful_n = int(len(prev_successful))

mkt = marketing_summary(sessions, successful, cpc_map)
mkt_prev = marketing_summary(sessions_prev, prev_successful, cpc_map)

render_hero(
    t(lang, "hero_kicker"),
    t(lang, "hero_title"),
    t(lang, "hero_subtitle"),
    t(lang, "hero_chip", bookings=backend_n),
)

if current is None:
    st.warning(t(lang, "no_sessions"))
    st.stop()


def _count_delta(cur, prev_n):
    if previous is None or not prev_n:
        return None
    return f"{(cur - prev_n) / prev_n:+.0%}"


def _rate_delta(key):
    if previous is None:
        return None
    return f"{(current[key] - previous[key]) * 100:+.1f} pp"


render_banner(t(lang, "marketing_banner_label"), t(lang, "marketing_banner_name"), "📣")
render_metric_cards(
    [
        {"label": t(lang, "leads"), "value": f"{mkt['leads']:,.0f}", "icon": "📈", "variant": "leads",
         "delta": _count_delta(mkt["leads"], mkt_prev["leads"])},
        {"label": t(lang, "revenue"), "value": format_money(mkt["revenue"]), "icon": "💶", "variant": "revenue",
         "delta": pct_change(mkt["revenue"], mkt_prev["revenue"] or None)},
        {"label": t(lang, "media_cost"), "value": format_money(mkt["cost"]), "icon": "📣", "variant": "cost",
         "delta": pct_change(mkt["cost"], mkt_prev["cost"] or None)},
        {"label": t(lang, "roas"), "value": f"{mkt['roas']:.2f}x" if mkt["roas"] else "—", "icon": "⚖️", "variant": "roas",
         "delta": pct_change(mkt["roas"], mkt_prev["roas"]) if mkt["roas"] and mkt_prev["roas"] else None},
    ],
    vs_label=t(lang, "vs_previous"),
)

render_metric_cards(
    [
        {"label": t(lang, "users"), "value": f"{current['users']:,.0f}", "icon": "👥",
         "delta": pct_change(current["users"], previous["users"] if previous else None)},
        {"label": t(lang, "sessions"), "value": f"{current['sessions']:,.0f}", "icon": "🧭",
         "delta": pct_change(current["sessions"], previous["sessions"] if previous else None)},
        {"label": t(lang, "engagement_rate"), "value": f"{current['engagement_rate']:.1%}", "icon": "⚡",
         "delta": _rate_delta("engagement_rate")},
        {"label": t(lang, "opened_booking"), "value": f"{current['booking_open_rate']:.1%}", "icon": "📝",
         "delta": _rate_delta("booking_open_rate")},
        {"label": t(lang, "real_bookings"), "value": f"{backend_n:,.0f}", "icon": "🚐", "variant": "accent",
         "delta": _count_delta(backend_n, prev_backend_n)},
    ],
    vs_label=t(lang, "vs_previous"),
)

dq_score = None
dq_findings: list[dict] = []
dq_row = None
if not dq_df.empty:
    dq_row = dq_df.iloc[0]
    dq_score = float(dq_row["cleanliness_score"]) if pd.notna(dq_row["cleanliness_score"]) else 0.0
    dq_findings = [
        {
            "issue": t(lang, "dq_issue_duplicates"),
            "before": t(
                lang,
                "dq_before_duplicates",
                bronze=int(dq_row["bronze_events"]),
            ),
            "after": t(
                lang,
                "dq_after_duplicates",
                silver=int(dq_row["silver_events"]),
                removed=int(dq_row["duplicate_events_removed"]),
            ),
        },
        {
            "issue": t(lang, "dq_issue_consent"),
            "before": t(
                lang,
                "dq_before_consent",
                consent=int(dq_row["consent_denied_events"]),
                debug=int(dq_row["debug_events"]),
            ),
            "after": t(lang, "dq_after_consent"),
        },
        {
            "issue": t(lang, "dq_issue_internal"),
            "before": t(
                lang,
                "dq_before_internal",
                events=int(dq_row["internal_events"]),
                sessions=int(dq_row["silver_sessions"]),
            ),
            "after": t(
                lang,
                "dq_after_internal",
                gold=int(dq_row["gold_sessions"]),
                excluded=int(dq_row["sessions_excluded_from_kpis"]),
            ),
        },
        {
            "issue": t(lang, "dq_issue_spam"),
            "before": t(lang, "dq_before_spam", spam=int(dq_row["spam_sessions"])),
            "after": t(lang, "dq_after_spam"),
        },
        {
            "issue": t(lang, "dq_issue_sessionless"),
            "before": t(lang, "dq_before_sessionless", n=int(dq_row["events_without_session"])),
            "after": t(lang, "dq_after_sessionless"),
        },
    ]

funnel_steps = [
    (t(lang, "funnel_session"), None),
    (t(lang, "funnel_opened"), "reached_booking_opened"),
    (t(lang, "funnel_form"), "reached_booking_form"),
    (t(lang, "funnel_submit"), "reached_booking_submit"),
    (t(lang, "funnel_created"), "reached_booking_success"),
]

(
    tab_overview,
    tab_data_quality,
    tab_marketing,
    tab_acquisition,
    tab_funnel,
    tab_content,
    tab_audience,
) = st.tabs([
    t(lang, "tab_overview"),
    t(lang, "tab_data_quality"),
    t(lang, "tab_marketing"),
    t(lang, "tab_acquisition"),
    t(lang, "tab_funnel"),
    t(lang, "tab_content"),
    t(lang, "tab_audience"),
])


# ---------------------------------------------------------------- overview

with tab_overview:
    day_label, week_label = t(lang, "day"), t(lang, "week")
    granularity = st.radio(t(lang, "granularity"), [day_label, week_label], horizontal=True, index=1)
    period_col = "session_date" if granularity == day_label else "session_week"
    trend = (
        sessions.groupby(period_col)
        .agg(
            users=("user_pseudo_id", "nunique"),
            sessions=("session_key", "size"),
            engaged_sessions=("is_engaged", "sum"),
            opened_booking=("reached_booking_opened", "sum"),
            clicked_submit=("reached_booking_submit", "sum"),
        )
        .reset_index()
        .rename(columns={period_col: "period"})
    )
    # Booking stars = backend bookings + offline seed (not web-analytics booking events).
    booking_trend = external_bookings.copy()
    if not booking_trend.empty:
        if granularity == day_label:
            booking_trend["period"] = pd.to_datetime(booking_trend["booked_date"])
        else:
            booking_trend["period"] = (
                pd.to_datetime(booking_trend["booked_date"])
                - pd.to_timedelta(pd.to_datetime(booking_trend["booked_date"]).dt.day_of_week, unit="D")
            )
        booking_counts = (
            booking_trend.groupby("period", as_index=False)
            .size()
            .rename(columns={"size": "bookings"})
        )
    else:
        booking_counts = pd.DataFrame(columns=["period", "bookings"])
    trend = trend.merge(booking_counts, on="period", how="left")
    if granularity == day_label:
        all_days = pd.DataFrame({"period": pd.date_range(start, end, freq="D")})
        trend = all_days.merge(trend, on="period", how="left")
    trend = trend.fillna(0)
    trend["engagement_rate"] = trend["engaged_sessions"] / trend["sessions"].where(trend["sessions"] > 0) * 100

    left, right = st.columns(2)
    with left:
        st.subheader(t(lang, "traffic"))
        rename = {
            "sessions": t(lang, "sessions"),
            "users": t(lang, "users"),
            "engaged_sessions": t(lang, "engaged_sessions"),
        }
        fig = px.line(
            trend.rename(columns=rename),
            x="period",
            y=list(rename.values()),
            markers=granularity == week_label,
            labels={"value": "", "period": "", "variable": ""},
            color_discrete_sequence=[PRIMARY, "#7FB89A", ACCENT],
        )
        fig.update_layout(legend=dict(orientation="h", y=1.12), margin=dict(t=10, b=10), height=340)
        st.plotly_chart(fig, width="stretch")
        if granularity == week_label:
            st.caption(t(lang, "week_caption"))
    with right:
        st.subheader(t(lang, "booking_intent"))
        fig = go.Figure()
        fig.add_bar(x=trend["period"], y=trend["opened_booking"], name=t(lang, "opened_booking_series"), marker_color="#7FB89A")
        fig.add_bar(x=trend["period"], y=trend["clicked_submit"], name=t(lang, "clicked_submit"), marker_color=PRIMARY)
        fig.add_scatter(
            x=trend["period"], y=trend["bookings"], name=t(lang, "bookings"), mode="markers",
            marker=dict(color=ACCENT, size=11, symbol="star"),
        )
        fig.update_layout(barmode="group", legend=dict(orientation="h", y=1.12), margin=dict(t=10, b=10), height=340)
        st.plotly_chart(fig, width="stretch")

    st.subheader(t(lang, "engagement_rate"))
    eng = trend.loc[trend["sessions"] > 0, ["period", "engagement_rate", "sessions"]].copy()
    fig = go.Figure()
    fig.add_scatter(
        x=eng["period"],
        y=eng["engagement_rate"],
        mode="lines+markers+text",
        name=t(lang, "engagement_rate"),
        line=dict(color=PRIMARY, width=2.5),
        marker=dict(size=9, color=PRIMARY),
        text=[f"{v:.0f}%" for v in eng["engagement_rate"]],
        textposition="top center",
        textfont=dict(size=11, color="#143528"),
        hovertemplate="%{x}<br>%{y:.1f}%<br>n=%{customdata}<extra></extra>",
        customdata=eng["sessions"],
    )
    # Zoom the y-axis around observed rates so ~10 pp gaps (e.g. the July dip) are visible.
    if not eng.empty:
        lo = float(eng["engagement_rate"].min())
        hi = float(eng["engagement_rate"].max())
        pad = max(8.0, (hi - lo) * 0.35)
        y0 = max(0.0, lo - pad)
        y1 = min(100.0, hi + pad)
        if y1 - y0 < 25:
            mid = (lo + hi) / 2
            y0, y1 = max(0.0, mid - 12.5), min(100.0, mid + 12.5)
    else:
        y0, y1 = 0, 100
    fig.update_layout(
        margin=dict(t=30, b=10),
        height=320,
        yaxis=dict(title="%", range=[y0, y1], ticksuffix="%"),
        xaxis=dict(title=""),
        showlegend=False,
    )
    st.plotly_chart(fig, width="stretch")

    st.subheader(t(lang, "highlights"))
    by_channel = group_metrics(sessions, "channel_group")
    by_landing = group_metrics(sessions, "landing_page_type")
    qualified = by_channel[by_channel["sessions"] >= 20]
    notes = [
        t(
            lang, "insight_top_channel",
            channel=by_channel.iloc[0]["channel_group"],
            n=int(by_channel.iloc[0]["sessions"]),
            pct=by_channel.iloc[0]["sessions"] / len(sessions),
        )
    ]
    if not qualified.empty:
        best = qualified.sort_values("booking_open_rate", ascending=False).iloc[0]
        worst = qualified.sort_values("booking_open_rate").iloc[0]
        notes.append(
            t(
                lang, "insight_best_intent",
                best=best["channel_group"], best_rate=best["booking_open_rate"],
                worst=worst["channel_group"], worst_rate=worst["booking_open_rate"],
            )
        )
    notes.append(
        t(lang, "insight_backend", backend=backend_n, successful=successful_n)
    )
    landing = by_landing.set_index("landing_page_type")
    if {"Home", "Trip page"} <= set(landing.index):
        notes[1:1] = [
            t(
                lang, "insight_landing",
                trip=landing.loc["Trip page", "booking_open_rate"],
                home=landing.loc["Home", "booking_open_rate"],
            )
        ]
    render_insights(notes[:3])


# ---------------------------------------------------------------- data quality

with tab_data_quality:
    st.caption(t(lang, "dq_tab_intro"))
    if dq_row is None or dq_score is None:
        st.info(t(lang, "no_sessions"))
    else:
        render_data_quality_panel(
            title=t(lang, "dq_title"),
            score=dq_score,
            score_caption=t(lang, "dq_caption"),
            findings=dq_findings,
            before_label=t(lang, "dq_before"),
            after_label=t(lang, "dq_after"),
            score_label=t(lang, "dq_score"),
        )
        st.subheader(t(lang, "dq_metrics_title"))
        dq_metric_keys = [
            "bronze_events",
            "silver_events",
            "duplicate_events_removed",
            "consent_denied_events",
            "debug_events",
            "internal_events",
            "events_without_session",
            "silver_sessions",
            "gold_sessions",
            "sessions_excluded_from_kpis",
            "spam_sessions",
            "cleanliness_score",
        ]
        metrics = pd.DataFrame(
            [
                {
                    t(lang, "dq_col_metric"): key,
                    t(lang, "dq_col_name"): t(lang, f"dq_m_{key}_name"),
                    t(lang, "dq_col_description"): t(lang, f"dq_m_{key}_desc"),
                    t(lang, "dq_col_value"): (
                        round(float(dq_score), 1)
                        if key == "cleanliness_score"
                        else int(dq_row[key])
                    ),
                }
                for key in dq_metric_keys
            ]
        )
        st.dataframe(
            metrics,
            width="stretch",
            hide_index=True,
            column_config={
                t(lang, "dq_col_metric"): st.column_config.TextColumn(width="medium"),
                t(lang, "dq_col_name"): st.column_config.TextColumn(width="medium"),
                t(lang, "dq_col_description"): st.column_config.TextColumn(width="large"),
                t(lang, "dq_col_value"): st.column_config.NumberColumn(format="%g"),
            },
        )

        st.subheader(t(lang, "dq_suspicious_title"))
        suspicious = sessions[sessions["is_spam_referrer"].astype(bool)].copy()
        # If the current filters hide all spam rows, still show the full-window
        # list so the presentation can explain what was found during cleaning.
        if suspicious.empty:
            suspicious = sessions_all[sessions_all["is_spam_referrer"].astype(bool)].copy()
        if suspicious.empty:
            st.info(t(lang, "dq_suspicious_empty"))
        else:
            st.caption(
                t(
                    lang,
                    "dq_suspicious_count",
                    sessions=int(len(suspicious)),
                    domains=int(suspicious["referrer_source"].fillna("(unknown)").nunique()),
                    users=int(suspicious["user_pseudo_id"].nunique()),
                )
            )
            suspicious_summary = (
                suspicious.assign(
                    referrer=suspicious["referrer_source"].fillna("(unknown)"),
                    reason=suspicious["referrer_source"].map(spam_reason_for),
                )
                .groupby(["referrer", "reason", "channel_group"], dropna=False)
                .agg(
                    sessions=("session_key", "size"),
                    users=("user_pseudo_id", "nunique"),
                )
                .reset_index()
                .sort_values("sessions", ascending=False)
            )
            suspicious_summary = suspicious_summary.rename(
                columns={
                    "referrer": t(lang, "dq_col_referrer"),
                    "reason": t(lang, "dq_col_reason"),
                    "channel_group": t(lang, "dq_col_channel"),
                    "sessions": t(lang, "sessions"),
                    "users": t(lang, "users"),
                }
            )
            st.dataframe(suspicious_summary, width="stretch", hide_index=True)


# ---------------------------------------------------------------- marketing

with tab_marketing:
    render_banner(t(lang, "marketing_banner_label"), t(lang, "marketing_banner_name"), "📣")
    st.subheader(t(lang, "marketing_by_channel"))

    by_ch = (
        sessions.groupby("channel_group", dropna=False)
        .agg(
            sessions=("session_key", "size"),
            users=("user_pseudo_id", "nunique"),
            leads=("reached_booking_opened", "sum"),
            submit_leads=("reached_booking_submit", "sum"),
        )
        .reset_index()
    )
    by_ch["estimated_media_cost"] = by_ch["channel_group"].map(cpc_map).fillna(0) * by_ch["sessions"]

    booked_ch = (
        successful.assign(channel_group=successful["channel_group"].fillna("Unattributed"))
        .groupby("channel_group", dropna=False)
        .agg(
            successful_bookings=("booking_id", "count"),
            estimated_revenue=("estimated_revenue", "sum"),
        )
        .reset_index()
    )
    by_ch = by_ch.merge(booked_ch, on="channel_group", how="outer").fillna(0)
    by_ch["lead_rate"] = (by_ch["leads"] / by_ch["sessions"].replace(0, float("nan")) * 100).astype(float)
    by_ch["cpl"] = by_ch["estimated_media_cost"] / by_ch["leads"].replace(0, float("nan"))
    by_ch["roas"] = by_ch["estimated_revenue"] / by_ch["estimated_media_cost"].replace(0, float("nan"))
    by_ch = by_ch.sort_values("sessions", ascending=False)

    st.dataframe(
        by_ch[[
            "channel_group", "sessions", "users", "leads", "submit_leads",
            "successful_bookings", "estimated_revenue", "estimated_media_cost",
            "lead_rate", "cpl", "roas",
        ]],
        hide_index=True,
        width="stretch",
        column_config={
            "channel_group": t(lang, "channel"),
            "sessions": t(lang, "sessions"),
            "users": t(lang, "users"),
            "leads": t(lang, "leads"),
            "submit_leads": t(lang, "clicked_submit"),
            "successful_bookings": t(lang, "successful_bookings"),
            "estimated_revenue": st.column_config.NumberColumn(t(lang, "revenue"), format="€%.0f"),
            "estimated_media_cost": st.column_config.NumberColumn(t(lang, "media_cost"), format="€%.0f"),
            "lead_rate": st.column_config.NumberColumn(t(lang, "opened_booking"), format="%.1f%%"),
            "cpl": st.column_config.NumberColumn(t(lang, "cpl"), format="€%.2f"),
            "roas": st.column_config.NumberColumn(t(lang, "roas"), format="%.2fx"),
        },
    )
    left, right = st.columns(2)
    with left:
        bar_cols = {"leads": t(lang, "leads"), "successful_bookings": t(lang, "successful_bookings")}
        fig = px.bar(
            by_ch.head(10).rename(columns=bar_cols), x="channel_group", y=list(bar_cols.values()),
            barmode="group",
            labels={"channel_group": "", "value": "", "variable": ""},
            color_discrete_sequence=["#3b82f6", PRIMARY],
        )
        fig.update_layout(legend=dict(orientation="h", y=1.12), margin=dict(t=10, b=10), height=340)
        st.plotly_chart(fig, width="stretch")
    with right:
        paid = by_ch[by_ch["estimated_media_cost"] > 0].copy()
        if paid.empty:
            st.info("—")
        else:
            fig = px.scatter(
                paid, x="estimated_media_cost", y="leads", size=paid["sessions"].clip(lower=1),
                color="channel_group", text="channel_group",
                labels={
                    "estimated_media_cost": t(lang, "media_cost"),
                    "leads": t(lang, "leads"),
                    "channel_group": "",
                },
                color_discrete_map=CHANNEL_COLORS,
            )
            fig.update_traces(textposition="top center")
            fig.update_layout(showlegend=False, margin=dict(t=10, b=10), height=340)
            st.plotly_chart(fig, width="stretch")

# ---------------------------------------------------------------- acquisition

with tab_acquisition:
    by_channel = group_metrics(sessions, "channel_group")
    left, right = st.columns([3, 2])
    with left:
        st.subheader(t(lang, "channel_performance"))
        show_table(by_channel.rename(columns={"channel_group": t(lang, "channel")}), lang)
    with right:
        st.subheader(t(lang, "volume_vs_intent"))
        fig = px.scatter(
            by_channel, x="sessions", y="booking_open_rate", size=by_channel["submit_sessions"] + 1,
            color="channel_group", color_discrete_map=CHANNEL_COLORS, text="channel_group", log_x=True,
            labels={
                "sessions": t(lang, "sessions_log"),
                "booking_open_rate": t(lang, "opened_booking_pct"),
                "channel_group": "",
            },
        )
        fig.update_traces(textposition="top center")
        fig.update_layout(showlegend=False, margin=dict(t=10, b=10), height=380)
        st.plotly_chart(fig, width="stretch")
        st.caption(t(lang, "bubble_caption"))

    st.subheader(t(lang, "channel_mix"))
    mix = sessions.groupby(["session_week", "channel_group"]).size().reset_index(name="sessions")
    fig = px.bar(
        mix, x="session_week", y="sessions", color="channel_group", color_discrete_map=CHANNEL_COLORS,
        labels={"session_week": t(lang, "week"), "sessions": t(lang, "sessions"), "channel_group": ""},
    )
    fig.update_layout(legend=dict(orientation="h", y=1.15), margin=dict(t=10, b=10), height=340)
    st.plotly_chart(fig, width="stretch")

    st.subheader(t(lang, "top_sources"))
    sources = group_metrics(
        sessions.assign(source_medium=sessions["source"] + " / " + sessions["medium"]),
        "source_medium",
    )
    show_table(sources.head(15).rename(columns={"source_medium": t(lang, "source_medium")}), lang)


# ---------------------------------------------------------------- funnel

with tab_funnel:
    values = [len(sessions)] + [int(sessions[col].sum()) for _, col in funnel_steps[1:]]
    st.subheader(t(lang, "booking_funnel"))
    fig = go.Figure(go.Funnel(
        y=[name for name, _ in funnel_steps], x=values,
        textinfo="value+percent initial+percent previous",
        marker=dict(color=["#B9D8C6", "#7FB89A", "#4E9A74", PRIMARY, ACCENT]),
    ))
    fig.update_layout(margin=dict(t=10, b=10), height=420)
    st.plotly_chart(fig, width="stretch")


# ---------------------------------------------------------------- content

with tab_content:
    st.subheader(t(lang, "landing_pages"))
    by_landing_page = group_metrics(sessions, "landing_page")
    show_table(by_landing_page.rename(columns={"landing_page": t(lang, "landing_page")}).head(20), lang)

    left, right = st.columns(2)
    with left:
        st.subheader(t(lang, "page_views"))
        st.caption(t(lang, "page_views_caption"))
        top_pages = pages.sort_values("page_views", ascending=False).head(12)
        fig = px.bar(
            top_pages, x="page_views", y="page_path", orientation="h",
            hover_data=["users", "avg_engagement_time_per_view_sec"],
            labels={"page_views": t(lang, "page_views_axis"), "page_path": ""},
            color_discrete_sequence=[PRIMARY],
        )
        fig.update_layout(yaxis=dict(autorange="reversed"), margin=dict(t=10, b=10), height=400)
        st.plotly_chart(fig, width="stretch")
    with right:
        st.subheader(t(lang, "destination_demand"))
        st.caption(t(lang, "destination_caption"))
        dest = destinations.sort_values("sessions_interested", ascending=True)
        fig = go.Figure()
        fig.add_bar(y=dest["destination_name"], x=dest["sessions_interested"], name=t(lang, "interested"),
                    orientation="h", marker_color="#B9D8C6")
        fig.add_bar(y=dest["destination_name"], x=dest["sessions_submitted"], name=t(lang, "submitted"),
                    orientation="h", marker_color=PRIMARY)
        fig.add_bar(y=dest["destination_name"], x=dest["sessions_booked"], name=t(lang, "booked"),
                    orientation="h", marker_color=ACCENT)
        fig.update_layout(barmode="overlay", legend=dict(orientation="h", y=1.1), margin=dict(t=10, b=10), height=400)
        st.plotly_chart(fig, width="stretch")


# ---------------------------------------------------------------- audience

with tab_audience:
    left, right = st.columns(2)
    with left:
        st.subheader(t(lang, "devices"))
        by_device = group_metrics(sessions, "device_category")
        fig = px.pie(
            by_device, names="device_category", values="sessions", hole=0.55,
            color_discrete_sequence=[PRIMARY, ACCENT, "#7FB89A", "#B9D8C6"],
        )
        fig.update_layout(margin=dict(t=10, b=10), height=300)
        st.plotly_chart(fig, width="stretch")
        show_table(by_device.rename(columns={"device_category": t(lang, "device")}), lang)
    with right:
        st.subheader(t(lang, "top_countries"))
        by_country = group_metrics(sessions, "country").head(12)
        fig = px.bar(
            by_country, x="sessions", y="country", orientation="h", color="booking_open_rate",
            color_continuous_scale=["#A9D3BB", "#14492F"],
            labels={
                "sessions": t(lang, "sessions"),
                "country": "",
                "booking_open_rate": t(lang, "opened_booking_pct_short"),
            },
        )
        fig.update_layout(yaxis=dict(autorange="reversed"), margin=dict(t=10, b=10), height=420)
        st.plotly_chart(fig, width="stretch")
