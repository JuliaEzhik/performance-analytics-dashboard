"""Capture README screenshots of the running dashboard.

Requires a running dashboard (default http://localhost:8501) and Playwright with a local Chrome:

    pip install playwright
    streamlit run dashboard/app.py
    python scripts/take_screenshots.py --url http://localhost:8501
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

TABS = [
    ("01-overview", "Overview"),
    ("02-data-quality", "Data quality"),
    ("03-marketing", "Marketing"),
    ("04-acquisition", "Acquisition"),
    ("05-booking-funnel", "Booking funnel"),
    ("06-content", "Content"),
    ("07-audience", "Audience"),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:8501")
    parser.add_argument("--out", default="docs/screenshots")
    parser.add_argument("--width", type=int, default=1500)
    args = parser.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": args.width, "height": 900}, device_scale_factor=1.5)
        page.goto(args.url, wait_until="networkidle")
        page.wait_for_selector("text=Performance Analysis Dashboard", timeout=60_000)
        page.wait_for_timeout(2500)

        for filename, label in TABS:
            page.get_by_role("tab", name=label, exact=True).click()
            page.wait_for_timeout(2500)
            # grow the viewport to the full content height so nothing is cut off
            content_height = page.evaluate(
                "Math.ceil(document.querySelector('[data-testid=\"stMainBlockContainer\"]')"
                ".getBoundingClientRect().bottom)"
            )
            page.set_viewport_size({"width": args.width, "height": max(700, int(content_height) + 40)})
            page.wait_for_timeout(1200)
            page.screenshot(path=str(out / f"{filename}.png"))
            print("saved", out / f"{filename}.png")

        browser.close()


if __name__ == "__main__":
    main()
