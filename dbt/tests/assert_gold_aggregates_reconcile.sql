-- Every gold aggregate must add up to the same session and booking totals as the session fact.
with totals as (
    select 'fct_sessions' as model, count(*) as sessions, sum(bookings) as bookings
    from {{ ref('gold_fct_sessions') }}
    union all
    select 'daily_kpis', sum(sessions), sum(bookings)
    from {{ ref('gold_agg_daily_kpis') }}
    union all
    select 'channel_performance', sum(sessions), sum(bookings)
    from {{ ref('gold_agg_channel_performance') }}
    union all
    select 'booking_funnel',
        sum(case when step_order = 0 then sessions else 0 end),
        sum(case when step_order = 4 then sessions else 0 end)
    from {{ ref('gold_agg_booking_funnel') }}
)

select *
from totals
where sessions != (select sessions from totals where model = 'fct_sessions')
   or (model != 'booking_funnel' and bookings != (select bookings from totals where model = 'fct_sessions'))
