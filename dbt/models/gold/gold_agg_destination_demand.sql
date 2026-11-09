-- Demand per destination, based on which destination the visitor had selected in the booking form.

with booking_form_events as (

    select
        events.session_key,
        events.event_name,
        events.destination_name
    from {{ ref('silver_events') }} as events
    inner join {{ ref('gold_fct_sessions') }} as sessions using (session_key)
    where events.destination_name is not null
      and (events.event_category = 'booking_form' or events.event_name = 'booking_submit_success')

)

select
    destination_name,
    count(distinct session_key) as sessions_interested,
    count(distinct session_key) filter (where event_name = 'booking_destination_select') as sessions_selected,
    count(distinct session_key) filter (where event_name = 'booking_submit_click') as sessions_submitted,
    count(distinct session_key) filter (where event_name = 'booking_submit_success') as sessions_booked,
    {{ safe_divide(
        "count(distinct session_key) filter (where event_name = 'booking_submit_click')",
        'count(distinct session_key)'
    ) }} as submit_rate
from booking_form_events
group by destination_name
