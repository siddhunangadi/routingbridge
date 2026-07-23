"""Design tokens and CSS injection for the RoutingBridge UI.

Split out from streamlit_app.py purely because the CSS block is long and
this keeps page logic readable — same "one clear responsibility per file"
rule used across the backend, not a new abstraction layer. Streamlit
doesn't expose a theming API rich enough for a warm-neutral, card-based
SaaS look, so this injects raw CSS once and provides small HTML-snippet
helpers the pages call directly.
"""

import streamlit as st

COLORS = {
    "bg": "#FAF7F1",
    "bg_sidebar": "#F3EEE4",
    "card": "#FFFFFF",
    "border": "#E8E1D3",
    "text": "#2B2A26",
    "text_muted": "#8A8073",
    "accent": "#6B7052",
    "accent_dark": "#565A42",
    "accent_soft": "#EDF0E6",
    "tier_basic": "#6E8A5E",
    "tier_standard": "#B08D4F",
    "tier_advanced": "#9C5B4A",
}

TIER_COLORS = {
    "BASIC": COLORS["tier_basic"],
    "STANDARD": COLORS["tier_standard"],
    "ADVANCED": COLORS["tier_advanced"],
}

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

html, body, [class*="css"], .stMarkdown, .stText {{
    font-family: 'Inter', -apple-system, sans-serif !important;
}}

.stApp {{
    background-color: {COLORS['bg']};
}}

#MainMenu, footer, header[data-testid="stHeader"] {{
    visibility: hidden;
    height: 0;
}}

section[data-testid="stSidebar"] {{
    background-color: {COLORS['bg_sidebar']};
    border-right: 1px solid {COLORS['border']};
}}
section[data-testid="stSidebar"] .block-container {{
    padding-top: 2rem;
}}

.block-container {{
    padding-top: 2.5rem;
    padding-bottom: 3rem;
    max-width: 1100px;
}}

h1 {{
    font-weight: 600 !important;
    letter-spacing: -0.02em;
    color: {COLORS['text']} !important;
    margin-bottom: 0.2em !important;
}}
h2, h3 {{
    font-weight: 600 !important;
    color: {COLORS['text']} !important;
    letter-spacing: -0.01em;
}}
p, span, label, div {{
    color: {COLORS['text']};
}}
.mp-subtitle {{
    color: {COLORS['text_muted']};
    font-size: 15px;
    margin-top: -8px;
    margin-bottom: 28px;
}}

/* sidebar nav (radio disguised as a nav list). The checked-dot color itself
   comes from .streamlit/config.toml's primaryColor, not from CSS here —
   Streamlit renders that dot via its own theme engine (emotion-generated
   classes), which a plain CSS override can't reliably win against. */
section[data-testid="stSidebar"] div[role="radiogroup"] label {{
    background: transparent;
    border-radius: 8px;
    padding: 9px 12px;
    margin-bottom: 2px;
    width: 100%;
}}
section[data-testid="stSidebar"] div[role="radiogroup"] label:hover {{
    background: {COLORS['card']};
}}

/* cards */
.mp-card {{
    background: {COLORS['card']};
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 16px;
    box-shadow: 0 1px 2px rgba(43,42,38,0.03);
}}
.mp-card-title {{
    font-size: 13px;
    font-weight: 600;
    color: {COLORS['text_muted']};
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 14px;
}}

/* native st.container(border=True, key="response_card"), restyled to
   match .mp-card. Used only here, where real Streamlit widgets (markdown-
   rendered LLM output) need to live inside a card — raw HTML string cards
   can't nest live widgets. Scoped via Streamlit's key= mechanism
   (-> .st-key-response_card), NOT the generic stVerticalBlockBorderWrapper
   testid — that testid is reused internally by Streamlit's own layout
   scaffolding (sidebar, main column), so targeting it globally boxes the
   entire page, not just this one container. */
div.st-key-response_card {{
    border: 1px solid {COLORS['border']} !important;
    border-radius: 12px !important;
    background: {COLORS['card']};
    box-shadow: 0 1px 2px rgba(43,42,38,0.03);
}}

/* metric tiles */
.mp-metric {{
    background: {COLORS['card']};
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
    padding: 18px 20px;
    box-shadow: 0 1px 2px rgba(43,42,38,0.03);
}}
.mp-metric-label {{
    font-size: 12.5px;
    color: {COLORS['text_muted']};
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 6px;
}}
.mp-metric-value {{
    font-size: 26px;
    font-weight: 600;
    color: {COLORS['text']};
    letter-spacing: -0.01em;
}}

/* routing decision key/value rows */
.mp-kv-row {{
    display: flex;
    justify-content: space-between;
    padding: 9px 0;
    border-bottom: 1px solid {COLORS['border']};
    font-size: 14.5px;
}}
.mp-kv-row:last-child {{ border-bottom: none; }}
.mp-kv-label {{ color: {COLORS['text_muted']}; }}
.mp-kv-value {{ color: {COLORS['text']}; font-weight: 500; }}

/* tier badge */
.mp-badge {{
    display: inline-block;
    padding: 3px 11px;
    border-radius: 999px;
    font-size: 12px;
    font-weight: 600;
    color: white;
    letter-spacing: 0.02em;
}}

/* inputs */
.stTextArea textarea, .stTextInput input {{
    border-radius: 10px !important;
    border: 1px solid {COLORS['border']} !important;
    background: {COLORS['card']} !important;
    font-family: 'Inter', sans-serif !important;
}}
.stTextArea textarea:focus, .stTextInput input:focus {{
    border-color: {COLORS['accent']} !important;
    box-shadow: 0 0 0 1px {COLORS['accent']} !important;
}}

.stButton > button {{
    background-color: {COLORS['accent']};
    color: white;
    border: none;
    border-radius: 8px;
    padding: 8px 20px;
    font-weight: 500;
    transition: background 0.15s ease;
}}
.stButton > button:hover {{
    background-color: {COLORS['accent_dark']};
    color: white;
}}
.stButton > button:focus:not(:active) {{
    color: white;
}}

/* dataframe */
[data-testid="stDataFrame"] {{
    border-radius: 10px;
    overflow: hidden;
    border: 1px solid {COLORS['border']};
}}

div[data-testid="stExpander"] {{
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
    background: {COLORS['card']};
}}

.mp-empty {{
    color: {COLORS['text_muted']};
    font-size: 14.5px;
    padding: 40px 0;
    text-align: center;
}}
</style>
"""


def inject_theme() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str) -> None:
    st.markdown(f"# {title}")
    st.markdown(f'<div class="mp-subtitle">{subtitle}</div>', unsafe_allow_html=True)


def metric_tile(label: str, value: str) -> str:
    return (
        f'<div class="mp-metric">'
        f'<div class="mp-metric-label">{label}</div>'
        f'<div class="mp-metric-value">{value}</div>'
        f"</div>"
    )


def tier_badge(tier: str) -> str:
    color = TIER_COLORS.get(tier, COLORS["text_muted"])
    return f'<span class="mp-badge" style="background:{color}">{tier}</span>'


def kv_row(label: str, value: str) -> str:
    return (
        f'<div class="mp-kv-row">'
        f'<span class="mp-kv-label">{label}</span>'
        f'<span class="mp-kv-value">{value}</span>'
        f"</div>"
    )
