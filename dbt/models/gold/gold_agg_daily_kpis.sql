-- Daily website KPIs: one row for every calendar day, plus rolling 7-day values.

with sessions as (

    select * from {{ ref('gold_fct_sessions') }}

),

backend_daily as (

    select
        booked_date as report_date,
        count(*) as backend_bookings,
        count(*) filter (where is_successful) as successful_bookings,
        count(*) filter (where is_cancelled) as cancelled_bookings,
        count(*) filter (where tracked_in_analytics) as tracked_bookings
    from {{ ref('gold_fct_bookings') }}
    where not is_internal_booking
    group by booked_date

),

calendar as (

    select cast(d as date) as report_date
    from generate_series(
        date '{{ var("start_date") }}',
        date '{{ var("end_date") }}',
        interval 1 day
    ) as t(d)

),

daily as (

    select
        session_date as report_date,
        count(distinct user_pseudo_id) as users,
        count(distinct user_pseudo_id) filter (where is_new_user) as new_users,
        count(*) as sessions,
        count(*) filter (where is_engaged) as engaged_sessions,
        sum(page_views) as page_views,
        sum(engagement_time_sec) as engagement_time_sec,
        sum(session_duration_sec) as session_duration_sec,
        count(*) filter (where reached_booking_opened) as booking_opened_sessions,
        count(*) filter (where reached_booking_form) as booking_form_sessions,
        count(*) filter (where reached_booking_submit) as booking_submit_sessions,
        sum(bookings) as bookings,
        count(*) filter (where is_spam_referrer) as spam_sessions
    from sessions
    group by session_date

),

consent_denied as (

    select event_date as report_date, count(*) filter (where event_name = 'page_view') as consent_denied_page_views
    from {{ ref('silver_events') }}
    where is_consent_denied
    group by event_date

),

joined as (

    select
        calendar.report_date,
        coalesce(daily.users, 0) as users,
        coalesce(daily.new_users, 0) as new_users,
        coalesce(daily.sessions, 0) as sessions,
        coalesce(daily.engaged_sessions, 0) as engaged_sessions,
        coalesce(daily.page_views, 0) as page_views,
        coalesce(daily.engagement_time_sec, 0) as engagement_time_sec,
        coalesce(daily.session_duration_sec, 0) as session_duration_sec,
        coalesce(daily.booking_opened_sessions, 0) as booking_opened_sessions,
        coalesce(daily.booking_form_sessions, 0) as booking_form_sessions,
        coalesce(daily.booking_submit_sessions, 0) as booking_submit_sessions,
        coalesce(daily.bookings, 0) as bookings,
        coalesce(daily.spam_sessions, 0) as spam_sessions,
        coalesce(consent_denied.consent_denied_page_views, 0) as consent_denied_page_views,
        coalesce(backend_daily.backend_bookings, 0) as backend_bookings,
        coalesce(backend_daily.successful_bookings, 0) as successful_bookings,
        coalesce(backend_daily.cancelled_bookings, 0) as cancelled_bookings,
        coalesce(backend_daily.tracked_bookings, 0) as tracked_bookings
    from calendar
    left join daily using (report_date)
    left join consent_denied using (report_date)
    left join backend_daily using (report_date)

)

select
    *,
    {{ safe_divide('engaged_sessions', 'sessions') }} as engagement_rate,
    {{ safe_divide('engagement_time_sec', 'sessions') }} as avg_engagement_time_sec,
    {{ safe_divide('page_views', 'sessions') }} as pages_per_session,
    {{ safe_divide('booking_opened_sessions', 'sessions') }} as booking_open_rate,
    {{ safe_divide('booking_submit_sessions', 'sessions') }} as booking_submit_rate,
    {{ safe_divide('bookings', 'sessions') }} as booking_conversion_rate,
    sum(sessions) over last_7_days as sessions_7d,
    sum(booking_submit_sessions) over last_7_days as booking_submit_sessions_7d,
    {{ safe_divide('sum(engaged_sessions) over last_7_days', 'sum(sessions) over last_7_days') }} as engagement_rate_7d
from joined
window last_7_days as (order by report_date range between interval 6 days preceding and current row)
