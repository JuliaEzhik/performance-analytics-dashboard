-- Pipeline data-quality snapshot: what was wrong in the raw data and what cleaning changed.
--
-- cleanliness_score = 100 - (consent-denied share x 40 + duplicate share x 30 + spam-session share x 30)

with bronze as (
    select count(*) as bronze_events
    from {{ ref('bronze_web_events') }}
),

silver_ev as (
    select
        count(*) as silver_events,
        count(*) filter (where is_consent_denied) as consent_denied_events,
        count(*) filter (where is_debug) as debug_events,
        count(*) filter (where is_internal_user) as internal_events,
        count(*) filter (where session_key is null) as events_without_session
    from {{ ref('silver_events') }}
),

silver_sess as (
    select
        count(*) as silver_sessions,
        count(*) filter (where is_internal) as internal_sessions,
        count(*) filter (where is_spam_referrer) as spam_sessions
    from {{ ref('silver_sessions') }}
),

gold_sess as (
    select count(*) as gold_sessions
    from {{ ref('gold_fct_sessions') }}
),

gold_book as (
    select
        count(*) as backend_bookings,
        count(*) filter (where not is_internal_booking) as external_bookings,
        count(*) filter (where not is_internal_booking and is_successful) as successful_bookings,
        count(*) filter (where is_internal_booking) as internal_bookings
    from {{ ref('gold_fct_bookings') }}
)

select
    bronze.bronze_events,
    silver_ev.silver_events,
    bronze.bronze_events - silver_ev.silver_events as duplicate_events_removed,
    silver_ev.consent_denied_events,
    silver_ev.debug_events,
    silver_ev.internal_events,
    silver_ev.events_without_session,
    silver_sess.silver_sessions,
    silver_sess.internal_sessions,
    silver_sess.spam_sessions,
    gold_sess.gold_sessions,
    silver_sess.silver_sessions - gold_sess.gold_sessions as sessions_excluded_from_kpis,
    gold_book.backend_bookings,
    gold_book.external_bookings,
    gold_book.successful_bookings,
    gold_book.internal_bookings,
    {{ safe_divide('bronze.bronze_events - silver_ev.silver_events', 'bronze.bronze_events') }} as duplicate_rate,
    {{ safe_divide('silver_sess.internal_sessions', 'silver_sess.silver_sessions') }} as internal_session_share,
    100 - (
        {{ safe_divide('silver_ev.consent_denied_events', 'silver_ev.silver_events') }} * 40
        + {{ safe_divide('bronze.bronze_events - silver_ev.silver_events', 'bronze.bronze_events') }} * 30
        + {{ safe_divide('silver_sess.spam_sessions', 'silver_sess.silver_sessions') }} * 30
    ) as cleanliness_score
from bronze
cross join silver_ev
cross join silver_sess
cross join gold_sess
cross join gold_book
