-- Cost per click (EUR) per paid channel: prefer the real ad-platform export,
-- otherwise fall back to the assumed values in the channel_cpc seed.

with ads_cpc as (

    select
        channel_group,
        avg(cast(avg_cpc as double)) as cpc,
        'ad_platform_export' as cpc_source,
        sum(cast(cost as double)) as reported_cost,
        sum(cast(clicks as bigint)) as reported_clicks,
        min(cast(period_start as date)) as cost_period_start,
        max(cast(period_end as date)) as cost_period_end
    from {{ ref('ads_campaign_export') }}
    group by channel_group

),

assumed_cpc as (

    select
        channel_group,
        cast(cpc as double) as cpc,
        'assumed_seed' as cpc_source,
        cast(null as double) as reported_cost,
        cast(null as bigint) as reported_clicks,
        cast(null as date) as cost_period_start,
        cast(null as date) as cost_period_end
    from {{ ref('channel_cpc') }}
    where channel_group not in (select channel_group from ads_cpc)

)

select * from ads_cpc
union all
select * from assumed_cpc
