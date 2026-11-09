-- Sessions reaching each booking step, per month x channel x device. Steps are cumulative
-- ("reached at least"), so sessions can be summed across any dimension.

with sessions as (

    select * from {{ ref('gold_fct_sessions') }}

),

steps as (

    select 0 as step_order, 'Session' as step_name, 0 as min_step
    union all select 1, 'Opened booking', 1
    union all select 2, 'Filled booking form', 2
    union all select 3, 'Clicked submit', 3
    union all select 4, 'Booking created', 4

)

select
    sessions.session_month,
    sessions.channel_group,
    sessions.device_category,
    steps.step_order,
    steps.step_name,
    count(*) filter (where sessions.max_booking_step >= steps.min_step) as sessions
from sessions
cross join steps
group by all
