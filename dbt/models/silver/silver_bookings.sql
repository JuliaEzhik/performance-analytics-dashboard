-- Silver: backend bookings with destination attached. Historical versions of edited
-- bookings (is_current_version = false) are kept here and filtered in gold.

with bookings as (

    select * from {{ source('raw', 'bookings') }}

),

destinations as (

    select
        id,
        name as destination_name,
        -- Prices are typed as free text ("60", "€45", "75 EUR"): keep digits and the decimal point.
        try_cast(regexp_replace(price, '[^0-9.]', '', 'g') as double) as destination_price
    from {{ source('raw', 'destinations') }}

),

internal as (

    select customer_id, requester_name
    from {{ ref('internal_customers') }}

)

select
    bookings.id as booking_id,
    bookings.trip_date,
    bookings.trip_time,
    bookings.created_at as booked_at,
    cast(bookings.created_at as date) as booked_date,
    bookings.status,
    bookings.is_current_version,
    bookings.is_private,
    bookings.destination_id,
    destinations.destination_name,
    destinations.destination_price,
    bookings.father_booking_id,
    bookings.previous_version_id,
    bookings.people,
    bookings.customer_id,
    bookings.status in ('approved', 'confirmed', 'completed') as is_successful,
    bookings.status = 'cancelled' as is_cancelled,
    bookings.status = 'deleted' as is_deleted,
    exists (
        select 1
        from internal
        where internal.customer_id = bookings.customer_id
           or lower(internal.requester_name) = lower(bookings.customer_name)
    ) as is_internal_booking,
    -- Estimated revenue: list price x seats, only for successful bookings.
    case
        when bookings.status in ('approved', 'confirmed', 'completed')
            then destinations.destination_price * greatest(coalesce(bookings.people, 1), 1)
    end as estimated_revenue
from bookings
left join destinations on destinations.id = bookings.destination_id
