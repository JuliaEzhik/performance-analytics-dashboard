-- Per page: traffic from page views, and landing quality from sessions that entered on that page.

with sessions as (

    select session_key, landing_page, is_engaged, reached_booking_opened, reached_booking_submit, bookings
    from {{ ref('gold_fct_sessions') }}

),

page_events as (

    select
        events.page_path,
        count(*) filter (where events.event_name = 'page_view') as page_views,
        count(distinct events.user_pseudo_id) filter (where events.event_name = 'page_view') as users,
        sum(events.engagement_time_msec) / 1000 as engagement_time_sec,
        max(events.time_on_page_seconds) as max_time_on_page_seconds,
        arg_max(events.page_title, events.event_ts) as page_title
    from {{ ref('silver_events') }} as events
    inner join sessions using (session_key)
    group by events.page_path

),

landings as (

    select
        landing_page as page_path,
        count(*) as landing_sessions,
        {{ safe_divide('count(*) filter (where is_engaged)', 'count(*)') }} as landing_engagement_rate,
        {{ safe_divide('count(*) filter (where reached_booking_opened)', 'count(*)') }} as landing_booking_open_rate,
        {{ safe_divide('count(*) filter (where reached_booking_submit)', 'count(*)') }} as landing_booking_submit_rate,
        sum(bookings) as landing_bookings
    from sessions
    group by landing_page

)

select
    page_events.page_path,
    page_events.page_title,
    case
        when page_events.page_path = '/' then 'Home'
        when starts_with(page_events.page_path, '/trips/') then 'Trip page'
        when page_events.page_path in ('/account', '/verify-email') then 'Account'
        else 'Other'
    end as page_type,
    page_events.page_views,
    page_events.users,
    {{ safe_divide('page_events.engagement_time_sec', 'nullif(page_events.page_views, 0)') }} as avg_engagement_time_per_view_sec,
    coalesce(landings.landing_sessions, 0) as landing_sessions,
    landings.landing_engagement_rate,
    landings.landing_booking_open_rate,
    landings.landing_booking_submit_rate,
    coalesce(landings.landing_bookings, 0) as landing_bookings
from page_events
left join landings using (page_path)
where page_events.page_views > 0
