from pathlib import Path
import html

import streamlit as st

STYLES_PATH = Path(__file__).parent / "styles.css"


def apply_styles() -> None:
    css = STYLES_PATH.read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def render_hero(kicker: str, title: str, subtitle: str, chip: str) -> None:
    kicker_html = f'<div class="hero-kicker">{html.escape(kicker)}</div>' if kicker else ""
    subtitle_html = (
        f'<div class="hero-tagline">{html.escape(subtitle)}</div>' if subtitle else ""
    )
    # st.html + compact markup: indented HTML in markdown becomes a code block.
    st.html(
        f'<div class="hero">'
        f'<div class="hero-copy">'
        f"{kicker_html}"
        f'<h1 class="hero-title">{html.escape(title)}</h1>'
        f"{subtitle_html}"
        f"</div>"
        f'<div class="hero-chip">{html.escape(chip)}</div>'
        f"</div>"
    )


def render_banner(label: str, name: str, icon: str = "🗂️") -> None:
    st.html(
        f'<div class="table-banner">'
        f'<div class="table-banner-icon">{icon}</div>'
        f"<div>"
        f'<div class="table-banner-label">{html.escape(label)}</div>'
        f'<div class="table-banner-name">{html.escape(name)}</div>'
        f"</div>"
        f"</div>"
    )


def _delta_html(delta: str | None, vs_label: str) -> str:
    if not delta:
        return ""
    down = delta.startswith("-") or delta.startswith("−")
    klass = "delta down" if down else "delta"
    return f'<div class="{klass}">{html.escape(delta)} {html.escape(vs_label)}</div>'


def render_metric_cards(cards: list[dict], vs_label: str = "vs previous period") -> None:
    cols = st.columns(len(cards))
    for col, card in zip(cols, cards):
        variant = card.get("variant", "")
        klass = f"metric-card {variant}".strip()
        with col:
            st.html(
                f'<div class="{klass}">'
                f'<div class="icon">{card.get("icon", "")}</div>'
                f'<div class="label">{html.escape(card["label"])}</div>'
                f'<div class="value">{html.escape(str(card["value"]))}</div>'
                f'{_delta_html(card.get("delta"), vs_label)}'
                f"</div>"
            )


def render_insights(notes: list[str]) -> None:
    cols = st.columns(len(notes)) if notes else []
    for col, note in zip(cols, notes):
        with col:
            st.markdown(f'<div class="insight">{note}</div>', unsafe_allow_html=True)


def render_data_quality_panel(
    title: str,
    score: float,
    score_caption: str,
    findings: list[dict],
    before_label: str = "Before",
    after_label: str = "After",
    score_label: str = "Score",
) -> None:
    """Compact data-quality strip: score + before/after cleaning findings."""
    if score >= 90:
        score_class = ""
    elif score >= 70:
        score_class = " warning"
    else:
        score_class = " danger"

    cards = "".join(
        (
            '<div class="dq-card">'
            f'<div class="dq-issue">{html.escape(item["issue"])}</div>'
            f'<div class="dq-before"><span>{html.escape(before_label)}</span>{html.escape(item["before"])}</div>'
            f'<div class="dq-after"><span>{html.escape(after_label)}</span>{html.escape(item["after"])}</div>'
            "</div>"
        )
        for item in findings
    )
    fill = min(max(score, 0), 100)

    # Use st.html so Markdown does not treat indented markup as a code block.
    st.html(
        f'<div class="dq-panel">'
        f'<div class="dq-header">'
        f"<div>"
        f'<div class="dq-title">{html.escape(title)}</div>'
        f'<div class="dq-caption">{html.escape(score_caption)}</div>'
        f"</div>"
        f'<div class="cleanliness-card{score_class} dq-scorebox">'
        f'<div class="cleanliness-header">'
        f'<span class="cleanliness-title">{html.escape(score_label)}</span>'
        f'<span class="cleanliness-score">{score:.0f}%</span>'
        f"</div>"
        f'<div class="cleanliness-track">'
        f'<div class="cleanliness-fill" style="width: {fill:.0f}%;"></div>'
        f"</div>"
        f"</div>"
        f"</div>"
        f'<div class="dq-grid">{cards}</div>'
        f"</div>"
    )
