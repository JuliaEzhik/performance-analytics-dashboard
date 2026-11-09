-- Every sessionised event must be counted in exactly one session.
with from_events as (
    select count(*) as n from {{ ref('silver_events') }} where session_key is not null
),

from_sessions as (
    select sum(events) as n from {{ ref('silver_sessions') }}
)

select from_events.n as events_with_session, from_sessions.n as events_in_sessions
from from_events cross join from_sessions
where from_events.n != from_sessions.n
