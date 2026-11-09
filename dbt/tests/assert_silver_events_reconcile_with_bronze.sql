-- Deduplication may only remove re-sent events (identical rows), never more than 1% of the
-- distinct bronze rows.
with bronze_distinct as (
    select count(*) as n
    from (
        select distinct * exclude (_loaded_at)
        from {{ ref('bronze_web_events') }}
    )
),

silver as (
    select count(*) as n from {{ ref('silver_events') }}
)

select bronze_distinct.n as bronze_distinct_rows, silver.n as silver_rows
from bronze_distinct cross join silver
where silver.n < bronze_distinct.n * 0.99
   or silver.n > bronze_distinct.n
