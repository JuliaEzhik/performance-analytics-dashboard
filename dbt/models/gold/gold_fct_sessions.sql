-- Gold: one row per external session (internal / debug traffic removed), with
-- reporting-friendly dimensions and booking funnel flags. The dashboard reads this table.

select
    session_key,
    user_pseudo_id,
    session_date,
    cast(date_trunc('week', session_date) as date) as session_week,
    cast(date_trunc('month', session_date) as date) as session_month,
    session_start_ts,
    is_new_user,

    channel_group,
    source,
    medium,
    campaign,
    referrer_source,
    is_spam_referrer,

    landing_page,
    case
        when landing_page = '/' then 'Home'
        when starts_with(landing_page, '/trips/') then 'Trip page'
        when landing_page in ('/account', '/verify-email') then 'Account'
        else 'Other'
    end as landing_page_type,

    coalesce(device_category, 'unknown') as device_category,
    device_os,
    device_browser,
    coalesce(nullif(geo_country, ''), '(not set)') as country,
    geo_city as city,

    page_views,
    events,
    session_duration_sec,
    engagement_time_sec,
    is_engaged,
    max_scroll_percent,

    max_booking_step,
    reached_booking_opened,
    reached_booking_form,
    reached_booking_submit,
    reached_booking_success,
    booking_submit_clicks,
    bookings,
    booking_destination,
    opened_auth,
    auth_succeeded,
    registered,
    contacted

from {{ ref('silver_sessions') }}
where not is_internal
