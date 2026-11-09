{{ config(severity='warn') }}

-- A created-booking event should always carry the backend booking id.
select event_id, event_ts, session_key
from {{ ref('silver_events') }}
where event_name = 'booking_submit_success'
  and trip_id is null
