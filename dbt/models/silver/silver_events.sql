-- Silver: one row per event.
--   * typed columns, parsed dates / timestamps
--   * URLs normalised to a page_path
--   * exact duplicate events (tag re-sends) removed
--   * internal / debug / consent-denied traffic is FLAGGED, not removed

with bronze as (

    select * from {{ ref('bronze_web_events') }}

),

flattened as (

    select
        -- Rows identical on every business field are re-sent duplicates.
        md5(concat_ws('|',
            coalesce(user_pseudo_id, ''),
            cast(event_timestamp as varchar),
            event_name,
            coalesce(cast(session_id as varchar), ''),
            coalesce(page_location, ''),
            coalesce(event_category, ''),
            coalesce(destination_name, ''),
            coalesce(cast(trip_id as varchar), ''),
            coalesce(cast(engagement_time_msec as varchar), ''),
            coalesce(cast(scroll_percent as varchar), '')
        )) as event_id,

        cast(event_date as date) as event_date,
        make_timestamp(event_timestamp) as event_ts,
        event_name,

        user_pseudo_id,
        session_id as ga_session_id,
        session_number as ga_session_number,
        user_pseudo_id is null as is_consent_denied,

        page_location,
        page_title,
        page_referrer,

        engagement_time_msec,
        coalesce(session_engaged = '1', false) as is_session_engaged_flag,

        event_category,
        destination_name,
        trip_id,
        scroll_percent,
        time_seconds as time_on_page_seconds,

        utm_source as event_source,
        utm_medium as event_medium,
        utm_campaign as event_campaign,
        gclid,
        gad_source,

        lower(device_category) as device_category,
        device_os,
        device_browser,
        device_language,
        geo_country,
        geo_city,

        coalesce(
            debug_mode is not null or page_referrer like '%tagassistant.google.com%',
            false
        ) as is_debug,

        _source_date,
        _loaded_at

    from bronze

),

normalized as (

    select
        *,
        nullif(regexp_extract(page_location, '^https?://([^/:?#]+)', 1), '') as page_hostname,
        coalesce(
            nullif(
                regexp_replace(
                    regexp_replace(lower(page_location), '^https?://[^/]+|[?#].*$', '', 'g'),
                    '(.)/$', '\1'
                ),
                ''
            ),
            '/'
        ) as page_path,
        nullif(regexp_extract(page_referrer, '^https?://([^/:?#]+)', 1), '') as referrer_host,
        case
            when user_pseudo_id is not null and ga_session_id is not null
                then user_pseudo_id || '.' || cast(ga_session_id as varchar)
        end as session_key,

        case
            when event_name = 'booking_submit_success' then 4
            when event_name = 'booking_submit_click' then 3
            when event_name in (
                'booking_destination_select', 'booking_calendar_nav_click', 'booking_time_filter_click'
            ) then 2
            when event_name in ('view_trip_booking', 'booking_start_click') then 1
        end as booking_step

    from flattened

),

deduplicated as (

    select *
    from normalized
    qualify row_number() over (partition by event_id order by _loaded_at) = 1

)

select
    *,
    user_pseudo_id is not null
        and bool_or(starts_with(page_path, '/admin') or is_debug) over (partition by user_pseudo_id)
        as is_internal_user
from deduplicated
