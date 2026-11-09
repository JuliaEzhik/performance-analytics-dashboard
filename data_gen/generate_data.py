"""Generate a fully synthetic "raw" layer for the performance analysis dashboard.

Everything here is invented: visitors, sessions, destinations, prices, bookings and
campaign numbers are drawn from random distributions with a fixed seed. No real
business, customer or traffic data is used.

The script writes three raw tables into a local DuckDB file (schema ``raw``):

* ``raw.web_events``   - web-analytics style event stream (one row per event)
* ``raw.bookings``     - booking backend export (several versions per booking)
* ``raw.destinations`` - destination catalogue with free-text prices

dbt then turns these into bronze -> silver -> gold models (see ``dbt/``).

Usage:
    python data_gen/generate_data.py [--db data/warehouse.duckdb] [--seed 42]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

START = date(2025, 6, 1)
END = date(2025, 9, 30)
SITE = "trips.example"

# Ad campaign (see dbt/seeds/ads_campaign_export.csv) that drives a burst of Paid Display clicks.
CAMPAIGN_START = date(2025, 7, 9)
CAMPAIGN_END = date(2025, 7, 31)

DESTINATIONS = [
    # slug, name, price text as typed in the catalogue, popularity weight
    ("lake-kayak-day", "Lake Kayak Day", "60", 1.6),
    ("sunrise-ridge-hike", "Sunrise Ridge Hike", "€45", 1.5),
    ("old-town-walk", "Old Town Walking Tour", "25", 1.2),
    ("cliffside-cable-car", "Cliffside Cable Car", "€38", 1.0),
    ("vineyard-tasting", "Vineyard Tasting", "75 EUR", 1.1),
    ("hot-springs-retreat", "Hot Springs Retreat", "€90", 0.8),
    ("canyon-cave-trip", "Canyon & Cave Trip", "110", 0.7),
    ("glacier-viewpoint", "Glacier Viewpoint", "€140", 0.5),
]

SPAM_DOMAINS = [
    "cheap-redirect-hub.example",
    "ad-popunder-net.example",
    "click-traffic-boost.example",
    "free-gifts-portal.example",
    "promo-offer-redirect.example",
    "adserve-partner-zone.example",
]

REFERRAL_DOMAINS = [
    "trail-notes.example",
    "localguides.example",
    "weekend-escapes.example",
    "city-break-blog.example",
    "family-outings.example",
    "deal-roundup.example",
]

PARTNER_SITES = [  # ad-network partner placements used by Paid Display
    "news-portal.example",
    "recipe-corner.example",
    "weather-today.example",
    "sports-scores.example",
    "game-arcade.example",
]

COUNTRIES = {
    # country: (weight, cities, language)
    "Germany": (0.30, ["Berlin", "Munich", "Hamburg", "Cologne", "Frankfurt"], "de-de"),
    "United States": (0.12, ["New York", "Austin", "Seattle", "Chicago"], "en-us"),
    "United Kingdom": (0.10, ["London", "Manchester", "Bristol"], "en-gb"),
    "France": (0.07, ["Paris", "Lyon", "Lille"], "fr-fr"),
    "Netherlands": (0.06, ["Amsterdam", "Utrecht", "Rotterdam"], "nl-nl"),
    "Italy": (0.05, ["Milan", "Rome", "Turin"], "it-it"),
    "Poland": (0.04, ["Warsaw", "Krakow"], "pl-pl"),
    "Spain": (0.05, ["Madrid", "Barcelona", "Valencia"], "es-es"),
    "Austria": (0.05, ["Vienna", "Graz", "Salzburg"], "de-at"),
    "Switzerland": (0.04, ["Zurich", "Basel", "Bern"], "de-ch"),
    "Canada": (0.03, ["Toronto", "Vancouver"], "en-ca"),
    "Sweden": (0.02, ["Stockholm", "Gothenburg"], "sv-se"),
    "Other": (0.03, ["(not set)"], "en-us"),
}
SPAM_COUNTRIES = ["India", "Vietnam", "Brazil", "Indonesia", "Turkey"]

OS_BY_DEVICE = {
    "mobile": [("Android", 0.52), ("iOS", 0.48)],
    "desktop": [("Windows", 0.55), ("Macintosh", 0.35), ("Linux", 0.10)],
    "tablet": [("iOS", 0.7), ("Android", 0.3)],
    "smart tv": [("Android", 1.0)],
}
BROWSER_BY_OS = {
    "Android": ["Chrome", "Samsung Internet", "Firefox"],
    "iOS": ["Safari", "Chrome"],
    "Windows": ["Chrome", "Edge", "Firefox"],
    "Macintosh": ["Safari", "Chrome"],
    "Linux": ["Firefox", "Chrome"],
}


@dataclass(frozen=True)
class ChannelProfile:
    weight: float  # share of regular (non-campaign) traffic
    p_engaged_boost: float  # extra readiness to browse beyond the landing page
    mean_extra_pages: float
    p_open_booking: float  # chance the session opens the booking flow
    p_new_user: float
    trip_landing: float  # share of sessions landing directly on a destination page


PROFILES: dict[str, ChannelProfile] = {
    "Organic Search": ChannelProfile(0.30, 0.55, 1.9, 0.115, 0.72, 0.42),
    "Direct": ChannelProfile(0.19, 0.60, 1.8, 0.100, 0.45, 0.14),
    "Organic Social": ChannelProfile(0.12, 0.40, 1.1, 0.065, 0.84, 0.50),
    "Referral": ChannelProfile(0.07, 0.50, 1.5, 0.085, 0.80, 0.38),
    "AI Assistant": ChannelProfile(0.025, 0.65, 2.2, 0.190, 0.86, 0.60),
    "Email": ChannelProfile(0.045, 0.70, 2.4, 0.180, 0.12, 0.45),
    "Paid Search": ChannelProfile(0.075, 0.55, 1.7, 0.135, 0.85, 0.72),
    "Paid Video": ChannelProfile(0.012, 0.30, 0.8, 0.040, 0.92, 0.35),
    "Paid Display": ChannelProfile(0.0, 0.30, 0.7, 0.028, 0.93, 0.30),  # campaign only
    "Display": ChannelProfile(0.012, 0.28, 0.7, 0.030, 0.90, 0.30),
    "Spam Referral": ChannelProfile(0.065, 0.0, 0.0, 0.0, 0.97, 0.0),
}

HOUR_WEIGHTS = np.array(
    [1, 1, 1, 1, 1, 2, 3, 5, 7, 8, 9, 9, 9, 9, 8, 8, 9, 10, 11, 12, 11, 8, 5, 3], dtype=float
)
HOUR_WEIGHTS /= HOUR_WEIGHTS.sum()

FIRST_NAMES = ["Alex", "Sam", "Jordan", "Taylor", "Robin", "Casey", "Jamie", "Morgan", "Riley", "Quinn",
               "Charlie", "Dana", "Eli", "Frankie", "Gray", "Harper", "Indy", "Jules", "Kai", "Lou"]
LAST_NAMES = ["Miller", "Schmidt", "Brown", "Rossi", "Dubois", "Novak", "Jansen", "Lopez", "Berg", "Weber"]


class Generator:
    def __init__(self, seed: int):
        self.rng = np.random.default_rng(seed)
        self.events: list[dict] = []
        self.bookings: list[dict] = []
        self.users: list[dict] = []  # returning-visitor pool
        self.next_booking_id = 1000
        self.admin_ids = [self._new_user_id() for _ in range(4)]
        self.admin_session_counts = {uid: 0 for uid in self.admin_ids}
        self.internal_customer_ids = [9100 + i for i in range(3)]

    # ------------------------------------------------------------------ helpers
    def _choice(self, options, probs=None):
        return options[self.rng.choice(len(options), p=probs)]

    def _new_user_id(self) -> str:
        return f"{self.rng.integers(10**8, 10**9)}.{self.rng.integers(1_700_000_000, 1_760_000_000)}"

    def _country(self, spam: bool) -> tuple[str, str, str]:
        if spam:
            country = self._choice(SPAM_COUNTRIES)
            return country, "(not set)", "en-us"
        names = list(COUNTRIES)
        weights = np.array([COUNTRIES[c][0] for c in names])
        country = self._choice(names, weights / weights.sum())
        _, cities, language = COUNTRIES[country]
        return country, self._choice(cities), language

    def _device(self, spam: bool) -> tuple[str, str, str]:
        if spam:
            device = self._choice(["desktop", "smart tv", "mobile"], [0.7, 0.2, 0.1])
        else:
            device = self._choice(["mobile", "desktop", "tablet"], [0.62, 0.34, 0.04])
        oses, weights = zip(*OS_BY_DEVICE[device])
        os_name = self._choice(list(oses), np.array(weights) / sum(weights))
        browser = self._choice(BROWSER_BY_OS[os_name])
        return device, os_name, browser

    def _start_time(self, day: date) -> datetime:
        hour = int(self.rng.choice(24, p=HOUR_WEIGHTS))
        return datetime(day.year, day.month, day.day, hour, int(self.rng.integers(0, 60)),
                        int(self.rng.integers(0, 60)), tzinfo=timezone.utc)

    # --------------------------------------------------------------- sessions
    def build_sessions(self) -> list[dict]:
        days = pd.date_range(START, END)
        channels = [c for c, p in PROFILES.items() if p.weight > 0]
        weights = np.array([PROFILES[c].weight for c in channels])
        weights /= weights.sum()
        sessions: list[dict] = []

        for i, ts in enumerate(days):
            day = ts.date()
            growth = 1.0 + 0.45 * i / len(days)
            weekend = 1.28 if day.weekday() >= 4 else 1.0
            lam = 92 * growth * weekend
            n_regular = int(self.rng.poisson(lam))
            for _ in range(n_regular):
                channel = self._choice(channels, weights)
                # Paid Search only runs after mid June; AI assistants grow over time
                if channel == "Paid Search" and day < date(2025, 6, 14):
                    channel = "Organic Search"
                if channel == "AI Assistant" and self.rng.random() > 0.4 + 0.6 * i / len(days):
                    channel = "Organic Search"
                sessions.append({"day": day, "channel": channel})

            if CAMPAIGN_START <= day <= CAMPAIGN_END:
                for _ in range(int(self.rng.poisson(52))):
                    # A large share of "paid" display clicks land on junk placements.
                    sessions.append({"day": day, "channel": "Paid Display"})

            # internal users (admins testing the product) and a few debug sessions
            if self.rng.random() < 0.55:
                sessions.append({"day": day, "channel": "Internal"})
        return sessions

    def simulate(self) -> None:
        for s in self.build_sessions():
            if s["channel"] == "Internal":
                self._internal_session(s["day"])
            else:
                self._visitor_session(s["day"], s["channel"])
        # consent-denied (cookieless) pings, no user or session identifiers
        self._consent_denied_pings()
        # a few events that are sent twice by the tag
        self._duplicate_events()
        # booking gaps: web bookings never seen in analytics + a few internal tests
        self._internal_bookings()

    # ----------------------------------------------------------------- events
    def _event(self, **kw) -> dict:
        base = {
            "event_date": None, "event_timestamp": None, "event_name": None,
            "user_pseudo_id": None, "session_id": None, "session_number": None,
            "page_location": None, "page_title": None, "page_referrer": None,
            "engagement_time_msec": None, "session_engaged": None,
            "event_category": None, "destination_name": None, "trip_id": None,
            "scroll_percent": None, "time_seconds": None,
            "utm_source": None, "utm_medium": None, "utm_campaign": None,
            "gclid": None, "gad_source": None,
            "device_category": None, "device_os": None, "device_browser": None,
            "device_language": None, "geo_country": None, "geo_city": None,
            "debug_mode": None,
        }
        base.update(kw)
        return base

    def _url(self, path: str, query: str = "") -> str:
        return f"https://www.{SITE}{path}{('?' + query) if query else ''}"

    def _page_for(self, path: str) -> str:
        if path == "/":
            return "Trips & experiences"
        if path.startswith("/trips/"):
            slug = path.split("/")[-1]
            name = next((d[1] for d in DESTINATIONS if d[0] == slug), slug)
            return f"{name} | Book online"
        return path.strip("/").replace("-", " ").title()

    def _landing(self, profile: ChannelProfile) -> str:
        r = self.rng.random()
        if r < profile.trip_landing:
            weights = np.array([d[3] for d in DESTINATIONS])
            d = self._choice(DESTINATIONS, weights / weights.sum())
            return f"/trips/{d[0]}"
        r2 = self.rng.random()
        if r2 < 0.72:
            return "/"
        if r2 < 0.80:
            return "/account"
        if r2 < 0.85:
            return "/verify-email"
        return self._choice(["/about", "/faq", "/blog/packing-tips", "/blog/summer-weekend-ideas", "/contact"])

    def _traffic_params(self, channel: str, rng_domain: str | None = None) -> dict:
        """Source/medium fields only appear on the first hit of a session, like in real tags."""
        out = {"page_referrer": None, "utm_source": None, "utm_medium": None, "utm_campaign": None,
               "gclid": None, "gad_source": None}
        gclid = lambda: "Cj0K" + "".join(self.rng.choice(list("abcdefghijklmnopqrstuvwxyz0123456789"), 18))  # noqa: E731
        if channel == "Organic Search":
            out["page_referrer"] = self._choice(
                ["https://www.google.com/", "https://www.google.de/", "https://www.bing.com/",
                 "https://duckduckgo.com/", "https://www.ecosia.org/"], [0.55, 0.15, 0.12, 0.1, 0.08])
        elif channel == "Direct":
            pass
        elif channel == "Organic Social":
            out["page_referrer"] = self._choice(
                ["https://l.facebook.com/", "https://www.instagram.com/", "https://t.co/",
                 "https://www.reddit.com/", "https://www.pinterest.com/", "https://www.youtube.com/"],
                [0.3, 0.3, 0.1, 0.1, 0.1, 0.1])
        elif channel == "Referral":
            out["page_referrer"] = f"https://{self._choice(REFERRAL_DOMAINS)}/post"
        elif channel == "AI Assistant":
            out["utm_source"] = self._choice(["chatgpt.com", "perplexity.ai", "gemini.google.com"], [0.7, 0.2, 0.1])
        elif channel == "Email":
            out["utm_source"], out["utm_medium"] = "newsletter", "email"
            out["utm_campaign"] = self._choice(["summer_deals", "weekend_picks", "welcome_series"])
        elif channel == "Paid Search":
            out["gclid"], out["gad_source"] = gclid(), "1"
            out["page_referrer"] = "https://www.google.com/"
        elif channel == "Paid Video":
            out["gclid"], out["gad_source"] = gclid(), "5"
            out["page_referrer"] = "https://www.youtube.com/"
        elif channel == "Paid Display":
            out["gclid"], out["gad_source"] = gclid(), "5"
            out["utm_campaign"] = "campaign_1_pmax"
            # partner placements; ~45% are junk adware / pop-under sites
            host = self._choice(SPAM_DOMAINS) if self.rng.random() < 0.45 else self._choice(PARTNER_SITES)
            out["page_referrer"] = f"https://{host}/"
        elif channel == "Display":
            out["utm_source"], out["utm_medium"] = self._choice(["taboola", "outbrain"]), "display"
        elif channel == "Spam Referral":
            out["page_referrer"] = f"https://{self._choice(SPAM_DOMAINS)}/"
        return out

    def _visitor_session(self, day: date, channel: str) -> None:
        profile = PROFILES[channel]
        spam_like = channel == "Spam Referral"
        traffic = self._traffic_params(channel)
        is_junk_display = channel == "Paid Display" and any(
            (traffic["page_referrer"] or "").startswith(f"https://{d}") for d in SPAM_DOMAINS)
        junk = spam_like or is_junk_display

        # user identity
        returning = self.users and self.rng.random() > profile.p_new_user
        if returning:
            user = self.users[int(self.rng.integers(len(self.users)))]
            user["sessions"] += 1
        else:
            user = {"id": self._new_user_id(), "sessions": 1}
            if not junk or self.rng.random() < 0.3:
                self.users.append(user)
        session_number = user["sessions"]

        start = self._start_time(day)
        session_id = int(start.timestamp())
        device, os_name, browser = self._device(junk)
        country, city, language = self._country(junk)
        ctx = dict(
            user_pseudo_id=user["id"], session_id=session_id, session_number=session_number,
            device_category=device, device_os=os_name, device_browser=browser,
            device_language=language, geo_country=country, geo_city=city,
        )

        landing = self._landing(profile)
        t = start
        engaged = False
        engagement_total = 0

        def emit(name: str, offset_s: float = 0.0, **kw):
            nonlocal t, engaged
            t = t + timedelta(seconds=offset_s, microseconds=int(self.rng.integers(0, 900_000)))
            row = self._event(
                event_date=t.date(), event_timestamp=int(t.timestamp() * 1_000_000) + int(self.rng.integers(0, 999)),
                event_name=name, session_engaged="1" if engaged else None, **ctx, **kw)
            self.events.append(row)
            return row

        if session_number == 1:
            emit("first_visit", page_location=self._url(landing), page_referrer=traffic["page_referrer"],
                 utm_source=traffic["utm_source"], utm_medium=traffic["utm_medium"],
                 utm_campaign=traffic["utm_campaign"], gclid=traffic["gclid"], gad_source=traffic["gad_source"])
        emit("session_start", 0.1, page_location=self._url(landing), page_referrer=traffic["page_referrer"],
             utm_source=traffic["utm_source"], utm_medium=traffic["utm_medium"],
             utm_campaign=traffic["utm_campaign"], gclid=traffic["gclid"], gad_source=traffic["gad_source"])
        emit("page_view", 0.2, page_location=self._url(landing), page_title=self._page_for(landing),
             page_referrer=traffic["page_referrer"], utm_source=traffic["utm_source"],
             utm_medium=traffic["utm_medium"], utm_campaign=traffic["utm_campaign"],
             gclid=traffic["gclid"], gad_source=traffic["gad_source"])

        if junk:
            # junk sessions bounce almost instantly, almost never engaged
            if self.rng.random() < 0.06:
                emit("user_engagement", 11.0, page_location=self._url(landing), engagement_time_msec=11_000)
            return

        # browsing
        current = landing
        extra_pages = int(self.rng.poisson(profile.mean_extra_pages * (0.6 + profile.p_engaged_boost)))
        if self.rng.random() > profile.p_engaged_boost + 0.15:
            extra_pages = 0  # quick bounce
        dwell = float(self.rng.gamma(2.0, 14.0))
        pages_path = [landing]
        for _ in range(extra_pages):
            dwell_ms = int(dwell * 1000)
            nxt = self._choice(
                ["/"] + [f"/trips/{d[0]}" for d in DESTINATIONS] + ["/about", "/faq", "/blog/packing-tips"],
                None)
            engagement_total += dwell_ms
            if engagement_total >= 10_000:
                engaged = True
            emit("user_engagement", dwell, page_location=self._url(current), engagement_time_msec=dwell_ms)
            if self.rng.random() < 0.5:
                emit("scroll", 1.0, page_location=self._url(current), scroll_percent=90)
            current = nxt
            pages_path.append(current)
            emit("page_view", 1.0, page_location=self._url(current), page_title=self._page_for(current),
                 page_referrer=self._url(pages_path[-2]))
            dwell = float(self.rng.gamma(2.0, 12.0))
        if self.rng.random() < profile.p_engaged_boost:
            dwell_ms = int(self.rng.gamma(2.0, 15.0) * 1000)
            engagement_total += dwell_ms
            if engagement_total >= 10_000 or extra_pages >= 1:
                engaged = True
            emit("user_engagement", dwell_ms / 1000, page_location=self._url(current), engagement_time_msec=dwell_ms)

        # booking funnel
        p_open = profile.p_open_booking
        if landing.startswith("/trips/"):
            p_open *= 1.8
        elif landing == "/":
            p_open *= 0.9
        else:
            p_open *= 0.35
        if landing in ("/account", "/verify-email"):
            p_open *= 0.3
        if self.rng.random() < min(p_open, 0.65):
            self._booking_flow(emit, current, landing, channel)
            engaged = True

        if self.rng.random() < 0.012:
            emit("auth_modal_open", 5, page_location=self._url(current), event_category="auth")
            if self.rng.random() < 0.5:
                emit("auth_success", 12, page_location=self._url(current), event_category="auth")
        if self.rng.random() < 0.01:
            emit("contact_form_submit_success", 8, page_location=self._url("/contact"), event_category="contact")

    def _booking_flow(self, emit, current: str, landing: str, channel: str) -> None:
        weights = np.array([d[3] for d in DESTINATIONS])
        if current.startswith("/trips/"):
            dest = next(d for d in DESTINATIONS if d[0] == current.split("/")[-1])
        else:
            dest = self._choice(DESTINATIONS, weights / weights.sum())
        page = self._url(f"/trips/{dest[0]}")
        emit("view_trip_booking", 6, page_location=page, event_category="booking_form", destination_name=dest[1])
        if self.rng.random() < 0.7:
            emit("booking_start_click", 3, page_location=page, event_category="booking_form", destination_name=dest[1])
        if self.rng.random() > 0.50:
            return
        emit("booking_destination_select", 8, page_location=page, event_category="booking_form", destination_name=dest[1])
        if self.rng.random() < 0.6:
            emit("booking_calendar_nav_click", 7, page_location=page, event_category="booking_form", destination_name=dest[1])
        if self.rng.random() < 0.4:
            emit("booking_time_filter_click", 5, page_location=page, event_category="booking_form", destination_name=dest[1])
        if self.rng.random() > 0.36:
            return
        emit("booking_submit_click", 14, page_location=page, event_category="booking_form", destination_name=dest[1])
        # A paid-display / video click converts far less often than other channels
        p_success = {"Paid Display": 0.10, "Paid Video": 0.2, "Display": 0.2}.get(channel, 0.48)
        if self.rng.random() > p_success:
            return
        booking = self._make_booking(emit_time=None, dest=dest, internal=False)
        submitted_at = self.events[-1]["event_timestamp"]
        booking["created_at"] = datetime.fromtimestamp(submitted_at / 1e6, tz=timezone.utc) + timedelta(seconds=3)
        self.bookings.append(booking)
        # analytics only sees ~92% of backend bookings (tracking gap)
        if self.rng.random() < 0.92:
            emit("booking_submit_success", 3, page_location=page, event_category="booking_form",
                 destination_name=dest[1], trip_id=booking["id"])

    def _make_booking(self, emit_time, dest, internal: bool, created_at: datetime | None = None) -> dict:
        bid = self.next_booking_id
        self.next_booking_id += 1
        status = self._choice(["approved", "completed", "requested", "cancelled", "deleted"],
                              [0.55, 0.12, 0.09, 0.17, 0.07])
        name = f"{self._choice(FIRST_NAMES)} {self._choice(LAST_NAMES)}"
        customer_id = int(self.rng.integers(20000, 90000))
        if internal:
            customer_id = int(self._choice(self.internal_customer_ids))
            name = f"Test Account {customer_id - 9099}"
        people = int(self._choice([1, 2, 3, 4, 5, 6], [0.26, 0.40, 0.14, 0.12, 0.05, 0.03]))
        return {
            "id": bid, "status": status, "is_current_version": True, "is_private": bool(self.rng.random() < 0.08),
            "destination_id": DESTINATIONS.index(dest) + 1, "people": people,
            "customer_id": customer_id, "customer_name": name,
            "father_booking_id": None, "previous_version_id": None,
            "created_at": created_at, "trip_date": None, "trip_time": None,
        }

    # ------------------------------------------------------ internal / misc
    def _internal_session(self, day: date) -> None:
        user_id = self._choice(self.admin_ids)
        self.admin_session_counts[user_id] += 1
        start = self._start_time(day)
        sid = int(start.timestamp())
        debug = self.rng.random() < 0.5
        ctx = dict(user_pseudo_id=user_id, session_id=sid, session_number=self.admin_session_counts[user_id],
                   device_category="desktop", device_os="Macintosh", device_browser="Chrome",
                   device_language="en-us", geo_country="Germany", geo_city="Berlin")
        t = start
        pages = ["/admin", "/admin/bookings", "/admin/reports", "/", "/trips/lake-kayak-day"]
        n = int(self.rng.integers(3, 9))
        for i in range(n):
            t += timedelta(seconds=float(self.rng.integers(4, 60)), microseconds=int(self.rng.integers(0, 900_000)))
            path = pages[min(i, len(pages) - 1)] if i < len(pages) else self._choice(pages)
            self.events.append(self._event(
                event_date=t.date(), event_timestamp=int(t.timestamp() * 1e6),
                event_name="page_view" if i % 2 == 0 else "user_engagement",
                page_location=self._url(path), page_title=self._page_for(path),
                page_referrer="https://tagassistant.google.com/" if debug and i == 0 else None,
                engagement_time_msec=int(self.rng.integers(2_000, 40_000)),
                session_engaged="1", debug_mode="1" if debug else None, **ctx))

    def _consent_denied_pings(self) -> None:
        total_page_views = sum(1 for e in self.events if e["event_name"] == "page_view")
        n = int(total_page_views * 0.12)
        days = pd.date_range(START, END)
        for _ in range(n):
            day = days[int(self.rng.integers(len(days)))].date()
            start = self._start_time(day)
            device, os_name, browser = self._device(False)
            country, city, language = self._country(False)
            landing = self._landing(PROFILES["Organic Search"])
            self.events.append(self._event(
                event_date=day, event_timestamp=int(start.timestamp() * 1e6) + int(self.rng.integers(0, 10**6)),
                event_name="page_view", page_location=self._url(landing), page_title=self._page_for(landing),
                device_category=device, device_os=os_name, device_browser=browser,
                device_language=language, geo_country=country, geo_city=city))

    def _duplicate_events(self) -> None:
        n = int(len(self.events) * 0.031)
        idx = self.rng.choice(len(self.events), size=n, replace=False)
        self.events.extend(dict(self.events[i]) for i in idx)

    def _internal_bookings(self) -> None:
        days = pd.date_range(START, END)
        # bookings that never produced an analytics event are already covered by the 8% gap above;
        # these are test bookings made by staff accounts.
        for _ in range(9):
            day = days[int(self.rng.integers(len(days)))].date()
            dest = DESTINATIONS[int(self.rng.integers(len(DESTINATIONS)))]
            created = self._start_time(day)
            b = self._make_booking(None, dest, internal=True, created_at=created)
            self.bookings.append(b)

    # ----------------------------------------------------------- finalise
    def finalise_bookings(self) -> pd.DataFrame:
        rows = []
        for b in self.bookings:
            created = b["created_at"]
            trip_date = (created + timedelta(days=int(self.rng.integers(3, 45)))).date()
            b["trip_date"] = trip_date
            b["trip_time"] = f"{int(self.rng.choice([8, 9, 10, 11, 13, 15]))}:{self._choice(['00', '30'])}"
            rows.append(b)
            # ~8% of bookings were edited: keep the old version as a non-current row
            if self.rng.random() < 0.08:
                old = dict(b)
                old["id"] = self.next_booking_id
                self.next_booking_id += 1
                old["status"] = "requested"
                old["is_current_version"] = False
                old["created_at"] = created - timedelta(minutes=int(self.rng.integers(2, 90)))
                old["father_booking_id"] = b["id"]
                rows.append(old)
                b["previous_version_id"] = old["id"]
        df = pd.DataFrame(rows).sort_values("id").reset_index(drop=True)
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True).dt.tz_localize(None)
        return df

    def destinations_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            [{"id": i + 1, "name": d[1], "slug": d[0], "price": d[2]} for i, d in enumerate(DESTINATIONS)]
        )

    def events_frame(self) -> pd.DataFrame:
        df = pd.DataFrame(self.events)
        df = df.sort_values("event_timestamp").reset_index(drop=True)
        for col in ("session_id", "session_number", "engagement_time_msec", "trip_id", "scroll_percent", "time_seconds"):
            df[col] = df[col].astype("Int64")
        df["event_date"] = pd.to_datetime(df["event_date"]).dt.date
        return df


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default="data/warehouse.duckdb")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    gen = Generator(args.seed)
    gen.simulate()
    events = gen.events_frame()
    bookings = gen.finalise_bookings()
    destinations = gen.destinations_frame()

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute("create schema if not exists raw")
    for name, df in (("web_events", events), ("bookings", bookings), ("destinations", destinations)):
        con.register("df_view", df)
        con.execute(f"create or replace table raw.{name} as select * from df_view").fetchall()
        n = con.execute(f"select count(*) from raw.{name}").fetchall()[0][0]
        con.unregister("df_view")
        print(f"raw.{name}: {n:,} rows")
    con.close()
    print(f"written to {db_path}")


if __name__ == "__main__":
    main()
