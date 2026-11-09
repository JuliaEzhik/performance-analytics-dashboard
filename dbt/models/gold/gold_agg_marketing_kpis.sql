-- Marketing KPIs for the reporting window:
--   leads         = sessions that opened the booking form
--   revenue       = estimated EUR from all successful external bookings (list price x people)
--   paid_revenue  = revenue only from bookings attributed to a paid channel
--   cost          = paid-channel sessions x cost per click (silver_channel_cpc)
--   ROAS          = paid_revenue / cost  (not total revenue: organic / offline bookings must not
--                   be credited to ads)

with sessions as (

    select * from {{ ref('gold_fct_sessions') }}

),

bookings as (

    select *
    from {{ ref('gold_fct_bookings') }}
    where not is_internal_booking
      and is_successful

),

cpc as (

    select channel_group, cpc from {{ ref('silver_channel_cpc') }}

),

session_kpis as (

    select
        count(distinct user_pseudo_id) as users,
        count(*) as sessions,
        count(*) filter (where is_engaged) as engaged_sessions,
        count(*) filter (where reached_booking_opened) as leads,
        count(*) filter (where reached_booking_submit) as submit_leads,
        sum(coalesce(cpc.cpc, 0)) as estimated_media_cost,
        count(*) filter (where cpc.cpc is not null) as paid_sessions
    from sessions
    left join cpc using (channel_group)

),

booking_kpis as (

    select
        count(*) as successful_bookings,
        coalesce(sum(estimated_revenue), 0) as estimated_revenue,
        coalesce(sum(estimated_revenue) filter (where channel_group in (select channel_group from cpc)), 0)
            as paid_attributed_revenue,
        count(*) filter (where channel_group in (select channel_group from cpc)) as paid_attributed_bookings
    from bookings

)

select
    session_kpis.users,
    session_kpis.sessions,
    session_kpis.engaged_sessions,
    session_kpis.leads,
    session_kpis.submit_leads,
    session_kpis.paid_sessions,
    session_kpis.estimated_media_cost,
    booking_kpis.successful_bookings,
    booking_kpis.estimated_revenue,
    booking_kpis.paid_attributed_revenue,
    booking_kpis.paid_attributed_bookings,
    {{ safe_divide('session_kpis.engaged_sessions', 'session_kpis.sessions') }} as engagement_rate,
    {{ safe_divide('session_kpis.leads', 'session_kpis.sessions') }} as lead_rate,
    {{ safe_divide('booking_kpis.successful_bookings', 'session_kpis.leads') }} as lead_to_booking_rate,
    {{ safe_divide('session_kpis.estimated_media_cost', 'session_kpis.leads') }} as cpl,
    {{ safe_divide('session_kpis.estimated_media_cost', 'session_kpis.paid_sessions') }} as avg_cpc,
    {{ safe_divide('booking_kpis.paid_attributed_revenue', 'session_kpis.estimated_media_cost') }} as roas,
    {{ safe_divide('booking_kpis.estimated_revenue', 'booking_kpis.successful_bookings') }} as revenue_per_booking
from session_kpis
cross join booking_kpis
