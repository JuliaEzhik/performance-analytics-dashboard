-- Silver: one row per session, with traffic attribution and a custom channel grouping.

with events as (

    select * from {{ ref('silver_events') }}
    where session_key is not null

),

sessions as (

    select
        session_key,
        any_value(user_pseudo_id) as user_pseudo_id,
        any_value(ga_session_id) as ga_session_id,
        max(ga_session_number) as ga_session_number,

        min(event_date) as session_date,
        min(event_ts) as session_start_ts,
        max(event_ts) as session_end_ts,

        count(*) as events,
        count(*) filter (where event_name = 'page_view') as page_views,
        count(distinct page_path) filter (where event_name = 'page_view') as unique_pages_viewed,
        coalesce(sum(engagement_time_msec), 0) / 1000 as engagement_time_sec,
        coalesce(bool_or(is_session_engaged_flag), false) as is_engaged,
        coalesce(bool_or(event_name = 'first_visit'), false) as has_first_visit,
        max(scroll_percent) as max_scroll_percent,

        arg_min(page_path, event_ts) filter (where event_name = 'page_view') as landing_page_from_view,
        arg_min(page_path, event_ts) as landing_page_any,
        arg_max(page_path, event_ts) as exit_page,

        -- Traffic attribution: source / medium are only sent on the session's first hits,
        -- so the earliest non-null value in the session wins.
        coalesce(bool_or(gclid is not null or gad_source is not null), false) as has_paid_click_id,
        any_value(gad_source) as gad_source,
        arg_min(event_source, event_ts) filter (where event_source is not null) as event_source,
        arg_min(event_medium, event_ts) filter (where event_source is not null) as event_medium,
        arg_min(event_campaign, event_ts) filter (where event_source is not null) as event_campaign,
        arg_min(referrer_host, event_ts) filter (
            where referrer_host is not null and not ends_with(referrer_host, '{{ var("site_domain") }}')
        ) as external_referrer_host,

        arg_min(device_category, event_ts) filter (where device_category is not null) as device_category,
        arg_min(device_os, event_ts) filter (where device_os is not null) as device_os,
        arg_min(device_browser, event_ts) filter (where device_browser is not null) as device_browser,
        arg_min(device_language, event_ts) filter (where device_language is not null) as device_language,
        arg_min(geo_country, event_ts) filter (where geo_country is not null) as geo_country,
        arg_min(geo_city, event_ts) filter (where geo_city is not null) as geo_city,

        coalesce(max(booking_step), 0) as max_booking_step,
        count(*) filter (where event_name = 'booking_submit_click') as booking_submit_clicks,
        count(*) filter (where event_name = 'booking_submit_success') as bookings,
        list(distinct trip_id) filter (where trip_id is not null) as booked_trip_ids,
        arg_max(destination_name, event_ts) filter (
            where event_category = 'booking_form' and destination_name is not null
        ) as booking_destination,
        coalesce(bool_or(event_name = 'auth_modal_open'), false) as opened_auth,
        coalesce(bool_or(event_name = 'auth_success'), false) as auth_succeeded,
        coalesce(bool_or(event_name = 'auth_registration_complete'), false) as registered,
        coalesce(bool_or(event_name in ('contact_form_submit_success', 'contact_detail_click')), false) as contacted,

        coalesce(bool_or(is_internal_user or is_debug), false) as is_internal

    from events
    group by session_key

),

attributed as (

    select
        sessions.*,
        coalesce(landing_page_from_view, landing_page_any) as landing_page,
        date_diff('second', session_start_ts, session_end_ts) as session_duration_sec,
        coalesce(ga_session_number = 1, false) or has_first_visit as is_new_user,

        lower(coalesce(event_source, external_referrer_host)) as referrer_source,
        case
            when has_paid_click_id then 'google'
            when event_source is not null then lower(event_source)
            when external_referrer_host is not null then lower(external_referrer_host)
            else '(direct)'
        end as source,
        case
            when has_paid_click_id then 'cpc'
            when event_source is not null then coalesce(lower(event_medium), 'referral')
            when external_referrer_host is not null then 'referral'
            else '(none)'
        end as medium,
        event_campaign as campaign

    from sessions

),

flagged as (

    select
        attributed.*,
        exists (
            select 1
            from {{ ref('spam_referrers') }} as spam
            where ends_with(attributed.referrer_source, lower(spam.referrer_domain))
        ) as is_spam_referrer
    from attributed

),

channeled as (

    select
        *,
        -- Ad clicks carry gad_source: 1 = Search, 5 = Display / Performance Max / video / partners.
        case
            when is_internal then 'Internal'
            when has_paid_click_id and regexp_matches(referrer_source, 'youtube') then 'Paid Video'
            when has_paid_click_id and gad_source = '1' then 'Paid Search'
            when has_paid_click_id and (gad_source = '5' or referrer_source is not null) then 'Paid Display'
            when has_paid_click_id or medium in ('cpc', 'ppc', 'paidsearch', 'paid') then 'Paid Other'
            when is_spam_referrer then 'Spam Referral'
            when regexp_matches(source, 'doubleclick|taboola|googlesyndication|outbrain')
                or medium in ('display', 'cpm', 'banner') then 'Display'
            when medium = 'ai-assistant'
                or regexp_matches(source, 'chatgpt|openai|perplexity|gemini|copilot|claude') then 'AI Assistant'
            when medium = 'organic'
                or regexp_matches(source, '(^|\.)(google|bing|yahoo|yandex|duckduckgo|ecosia|baidu)\.') then 'Organic Search'
            when medium in ('social', 'social-network', 'sm')
                or regexp_matches(source, 'facebook|instagram|^ig$|youtube|tiktok|twitter|^t\.co$|linkedin|pinterest|reddit') then 'Organic Social'
            when medium = 'email' then 'Email'
            when source = '(direct)' then 'Direct'
            when medium = 'referral' then 'Referral'
            else 'Unassigned'
        end as channel_group

    from flagged

)

select
    session_key,
    user_pseudo_id,
    ga_session_id,
    ga_session_number,
    is_new_user,
    session_date,
    session_start_ts,
    session_end_ts,
    session_duration_sec,

    source,
    medium,
    campaign,
    referrer_source,
    gad_source,
    channel_group,
    is_spam_referrer,

    landing_page,
    exit_page,
    events,
    page_views,
    unique_pages_viewed,
    engagement_time_sec,
    is_engaged,
    max_scroll_percent,

    device_category,
    device_os,
    device_browser,
    device_language,
    geo_country,
    geo_city,

    max_booking_step,
    max_booking_step >= 1 as reached_booking_opened,
    max_booking_step >= 2 as reached_booking_form,
    max_booking_step >= 3 as reached_booking_submit,
    max_booking_step >= 4 as reached_booking_success,
    booking_submit_clicks,
    bookings,
    booked_trip_ids,
    booking_destination,
    opened_auth,
    auth_succeeded,
    registered,
    contacted,

    is_internal

from channeled
