-- A later booking step can never have more sessions than the step before it.
select *
from (
    select
        session_month,
        channel_group,
        device_category,
        step_order,
        sessions,
        lag(sessions) over (
            partition by session_month, channel_group, device_category
            order by step_order
        ) as previous_step_sessions
    from {{ ref('gold_agg_booking_funnel') }}
)
where sessions > previous_step_sessions
