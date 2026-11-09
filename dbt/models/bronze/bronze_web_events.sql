-- Bronze: untouched copy of the raw event stream for the reporting window.
-- Only load metadata columns (prefixed with "_") are added.
select
    events.*,
    events.event_date as _source_date,
    current_timestamp as _loaded_at
from {{ source('raw', 'web_events') }} as events
where events.event_date between date '{{ var("start_date") }}' and date '{{ var("end_date") }}'
