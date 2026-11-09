-- Channel-level marketing performance (leads, revenue, cost, ROAS, CPL).

with session_rows as (

    select * from {{ ref('gold_fct_sessions') }}

),

cpc as (

    select channel_group, cpc from {{ ref('silver_channel_cpc') }}

),

booking_rollups as (

    select
        coalesce(channel_group, 'Unattributed') as channel_group,
        count(*) as successful_bookings,
        coalesce(sum(estimated_revenue), 0) as estimated_revenue
    from {{ ref('gold_fct_bookings') }}
    where not is_internal_booking
      and is_successful
    group by 1

),

session_rollups as (

    select
        session_rows.channel_group,
        count(distinct session_rows.user_pseudo_id) as users,
        count(*) as session_count,
        count(*) filter (where session_rows.is_engaged) as engaged_sessions,
        count(*) filter (where session_rows.reached_booking_opened) as leads,
        count(*) filter (where session_rows.reached_booking_submit) as submit_leads,
        sum(coalesce(cpc.cpc, 0)) as estimated_media_cost
    from session_rows
    left join cpc using (channel_group)
    group by session_rows.channel_group

)

select
    coalesce(session_rollups.channel_group, booking_rollups.channel_group) as channel_group,
    coalesce(session_rollups.users, 0) as users,
    coalesce(session_rollups.session_count, 0) as sessions,
    coalesce(session_rollups.engaged_sessions, 0) as engaged_sessions,
    coalesce(session_rollups.leads, 0) as leads,
    coalesce(session_rollups.submit_leads, 0) as submit_leads,
    coalesce(booking_rollups.successful_bookings, 0) as successful_bookings,
    coalesce(booking_rollups.estimated_revenue, 0) as estimated_revenue,
    coalesce(session_rollups.estimated_media_cost, 0) as estimated_media_cost,
    {{ safe_divide('session_rollups.engaged_sessions', 'session_rollups.session_count') }} as engagement_rate,
    {{ safe_divide('session_rollups.leads', 'session_rollups.session_count') }} as lead_rate,
    {{ safe_divide('coalesce(booking_rollups.successful_bookings, 0)', 'session_rollups.leads') }} as lead_to_booking_rate,
    {{ safe_divide('session_rollups.estimated_media_cost', 'session_rollups.leads') }} as cpl,
    -- Per-channel ROAS: only that channel's booking revenue / that channel's media cost.
    {{ safe_divide('coalesce(booking_rollups.estimated_revenue, 0)', 'session_rollups.estimated_media_cost') }} as roas
from session_rollups
full outer join booking_rollups using (channel_group)
