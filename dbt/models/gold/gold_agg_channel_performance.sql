select
    session_month,
    channel_group,
    count(distinct user_pseudo_id) as users,
    count(*) as sessions,
    count(*) filter (where is_engaged) as engaged_sessions,
    {{ safe_divide('count(*) filter (where is_engaged)', 'count(*)') }} as engagement_rate,
    avg(engagement_time_sec) as avg_engagement_time_sec,
    {{ safe_divide('sum(page_views)', 'count(*)') }} as pages_per_session,
    count(*) filter (where reached_booking_opened) as booking_opened_sessions,
    count(*) filter (where reached_booking_submit) as booking_submit_sessions,
    sum(bookings) as bookings,
    {{ safe_divide('count(*) filter (where reached_booking_opened)', 'count(*)') }} as booking_open_rate,
    {{ safe_divide('count(*) filter (where reached_booking_submit)', 'count(*)') }} as booking_submit_rate,
    {{ safe_divide('sum(bookings)', 'count(*)') }} as booking_conversion_rate,
    count(*) filter (where is_spam_referrer) as spam_sessions
from {{ ref('gold_fct_sessions') }}
group by all
