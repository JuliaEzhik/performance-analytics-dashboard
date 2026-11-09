-- Gold: one row per current backend booking created in the reporting window, plus the
-- offline (chat / phone) bookings from the seed. Customer names are never carried into gold.

with current_bookings as (

    select *
    from {{ ref('silver_bookings') }}
    where is_current_version
      and not is_deleted
      and booked_date between date '{{ var("start_date") }}' and date '{{ var("end_date") }}'

),

web_success as (

    select
        trip_id as booking_id,
        session_key,
        event_ts as tracked_at,
        page_path as booking_page
    from {{ ref('silver_events') }}
    where event_name = 'booking_submit_success'
      and trip_id is not null
    qualify row_number() over (partition by trip_id order by event_ts) = 1

),

backend_bookings as (

    select
        bookings.booking_id,
        bookings.booked_date,
        bookings.booked_at,
        bookings.trip_date,
        bookings.trip_time,
        bookings.status,
        bookings.is_successful,
        bookings.is_cancelled,
        bookings.is_private,
        bookings.destination_name,
        bookings.destination_price,
        bookings.estimated_revenue,
        bookings.people,
        bookings.is_internal_booking,
        false as is_seeded_booking,
        cast(null as varchar) as booking_channel,
        web_success.booking_id is not null as tracked_in_analytics,
        web_success.tracked_at,
        web_success.booking_page,
        sessions.session_key,
        sessions.user_pseudo_id,
        sessions.channel_group,
        sessions.source,
        sessions.medium,
        sessions.landing_page,
        sessions.device_category,
        sessions.country,
        sessions.is_new_user,
        case
            when web_success.tracked_at is not null and sessions.session_start_ts is not null
                then date_diff('second', sessions.session_start_ts, web_success.tracked_at)
        end as seconds_from_session_start
    from current_bookings as bookings
    left join web_success using (booking_id)
    left join {{ ref('gold_fct_sessions') }} as sessions
        on web_success.session_key = sessions.session_key

),

offline_seed as (

    select
        cast(booking_id as bigint) as booking_id,
        cast(booked_date as date) as booked_date,
        cast(booked_date as timestamp) as booked_at,
        cast(trip_date as date) as trip_date,
        cast(null as varchar) as trip_time,
        status,
        status in ('approved', 'confirmed', 'completed') as is_successful,
        status = 'cancelled' as is_cancelled,
        false as is_private,
        destination_name,
        cast(destination_price as double) as destination_price,
        case
            when status in ('approved', 'confirmed', 'completed')
                then cast(destination_price as double) * greatest(cast(people as bigint), 1)
        end as estimated_revenue,
        cast(people as bigint) as people,
        false as is_internal_booking,
        true as is_seeded_booking,
        booking_channel,
        false as tracked_in_analytics,
        cast(null as timestamp) as tracked_at,
        cast(null as varchar) as booking_page,
        cast(null as varchar) as session_key,
        cast(null as varchar) as user_pseudo_id,
        'Offline' as channel_group,
        'chat' as source,
        'offline' as medium,
        cast(null as varchar) as landing_page,
        cast(null as varchar) as device_category,
        cast(null as varchar) as country,
        cast(null as boolean) as is_new_user,
        cast(null as bigint) as seconds_from_session_start
    from {{ ref('offline_bookings') }}
    where cast(booked_date as date) between date '{{ var("start_date") }}' and date '{{ var("end_date") }}'

)

select * from backend_bookings
union all by name
select * from offline_seed
