"""RoutingBridge Streamlit UI.

One file, sidebar radio for navigation between four pages. No multipage
framework, no page-router abstraction — for four screens that each just
call one backend endpoint and render it, a single file with four small
functions is the whole solution. Visual design lives in theme.py; this
file is purely page layout and API calls — no backend/API changes here.
"""

import os
import time

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from theme import COLORS, inject_theme, kv_row, metric_tile, page_header, quality_badge, tier_badge

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="RoutingBridge", page_icon=None, layout="wide")
inject_theme()

CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Inter, sans-serif", color=COLORS["text"], size=13),
    margin=dict(l=10, r=10, t=10, b=10),
    showlegend=False,
)


def _get(path: str, **params) -> dict | list | None:
    try:
        resp = httpx.get(f"{BACKEND_URL}{path}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        st.error(f"Could not reach backend at {BACKEND_URL}{path}: {exc}")
        return None


def _post_chat_with_retry(prompt: str, max_wait_seconds: int = 60) -> dict | None:
    """POST /chat, retrying quietly through a Render free-tier cold start.

    A sleeping free-tier service returns Render's own HTML error page (no
    JSON body) while it wakes up — that's structurally different from our
    API's own errors, which are always JSON with a "detail" field. That
    distinction is what tells us whether to retry (platform waking up) or
    stop and show the real error (our API rejected the request). Retrying
    quietly for the ~30-60s a cold start takes is what lets a shared demo
    link survive someone's first cold click instead of showing raw HTML.
    """
    deadline = time.time() + max_wait_seconds
    attempt = 0
    status_box = st.empty()

    while True:
        attempt += 1
        try:
            resp = httpx.post(f"{BACKEND_URL}/chat", json={"prompt": prompt}, timeout=30)
        except httpx.HTTPError:
            resp = None

        if resp is not None:
            try:
                data = resp.json()
            except ValueError:
                data = None  # platform-level error page, not our API's JSON

            if data is not None:
                status_box.empty()
                if resp.status_code == 200:
                    return data
                st.error(data.get("detail", f"Request failed ({resp.status_code})."))
                return None

        if time.time() >= deadline:
            status_box.empty()
            st.error(
                "The backend is taking longer than expected to wake up. "
                "Please wait a moment and try again."
            )
            return None

        status_box.info(
            "Starting the AI service... this demo runs on a free hosting "
            "tier that sleeps after inactivity, so the first request can "
            f"take up to a minute. Retrying (attempt {attempt})..."
        )
        time.sleep(4)


def render_chat() -> None:
    page_header("Chat", "Every prompt is routed to the cheapest model that can handle it well.")

    prompt = st.text_area(
        "Prompt", height=120, placeholder="Ask anything...", label_visibility="collapsed"
    )
    send = st.button("Send", type="primary")

    if send and prompt.strip():
        data = _post_chat_with_retry(prompt)
        if data is None:
            return

        # A raw HTML string card (open-div/content/close-div across separate
        # st.markdown calls) doesn't actually nest — Streamlit renders each
        # call as an isolated fragment. Using a native bordered container
        # instead means st.write() still renders the model's own markdown
        # (bold, lists, code) correctly; theme.py restyles its border to
        # match the rest of the card system.
        with st.container(border=True, key="response_card"):
            st.markdown('<div class="mp-card-title">Response</div>', unsafe_allow_html=True)
            st.write(data["response"])

        left, right = st.columns([1, 1], gap="medium")

        with left:
            escalation_note = ""
            if data["escalated"]:
                escalation_note = kv_row(
                    "Escalated from", f"{data['original_tier']} (low confidence)"
                )
            rows = "".join(
                [
                    kv_row("Routing Tier", tier_badge(data["routing_tier"])),
                    kv_row("Provider", data["provider"]),
                    kv_row("Model", data["model"]),
                    kv_row("Task Type", data["task_type"]),
                    kv_row("Confidence", f"{data['confidence']:.2f}"),
                    escalation_note,
                ]
            )
            st.markdown(
                f'<div class="mp-card"><div class="mp-card-title">Routing Decision</div>{rows}</div>',
                unsafe_allow_html=True,
            )

        with right:
            fallback_note = " (heuristic fallback)" if data["fallback_used"] else ""
            rows = "".join(
                [
                    kv_row("Total Cost", f"${data['total_cost']:.6f}"),
                    kv_row("Model Cost", f"${data['model_cost']:.6f}"),
                    kv_row("Classifier Cost", f"${data['classifier_cost']:.6f}"),
                    kv_row("Latency", f"{data['total_latency_ms']:.0f} ms"),
                    kv_row("Classifier", f"{data['classifier_model']}{fallback_note}"),
                ]
            )
            st.markdown(
                f'<div class="mp-card"><div class="mp-card-title">Cost & Latency</div>{rows}</div>',
                unsafe_allow_html=True,
            )

        quality_rows = kv_row("Verdict", quality_badge(data["quality_passed"]))
        if data["quality_reason"]:
            quality_rows += kv_row("Reason", data["quality_reason"])
        st.markdown(
            f'<div class="mp-card"><div class="mp-card-title">Quality Check</div>{quality_rows}</div>',
            unsafe_allow_html=True,
        )

        with st.expander("Why this model was selected"):
            for reason in data["routing_reason"]:
                st.write(f"— {reason}")


def render_history() -> None:
    page_header("History", "Every request this app has routed, most recent first.")

    rows = _get("/history", limit=200)
    if rows is None:
        return
    if not rows:
        st.markdown('<div class="mp-empty">No requests yet — try the Chat page.</div>', unsafe_allow_html=True)
        return

    df = pd.DataFrame(rows)

    col_search, col_filter = st.columns([2, 1])
    with col_search:
        search = st.text_input("Search prompts", placeholder="Search prompts...")
    with col_filter:
        tiers = ["All"] + sorted(df["routing_tier"].unique().tolist())
        tier_filter = st.selectbox("Routing tier", tiers)

    if search:
        df = df[df["prompt"].str.contains(search, case=False, na=False)]
    if tier_filter != "All":
        df = df[df["routing_tier"] == tier_filter]

    if df.empty:
        st.markdown('<div class="mp-empty">No requests match this filter.</div>', unsafe_allow_html=True)
        return

    display_df = df[
        [
            "timestamp",
            "prompt",
            "routing_tier",
            "provider",
            "model",
            "total_cost",
            "total_latency_ms",
            "fallback_used",
        ]
    ].rename(
        columns={
            "timestamp": "Time",
            "prompt": "Prompt",
            "routing_tier": "Tier",
            "provider": "Provider",
            "model": "Model",
            "total_cost": "Cost ($)",
            "total_latency_ms": "Latency (ms)",
            "fallback_used": "Fallback",
        }
    )

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Cost ($)": st.column_config.NumberColumn(format="$%.6f"),
            "Latency (ms)": st.column_config.NumberColumn(format="%.0f"),
        },
    )


def _bar_chart(labels: list[str], values: list[float], color: str) -> go.Figure:
    fig = go.Figure(
        go.Bar(x=values, y=labels, orientation="h", marker_color=color, marker_line_width=0)
    )
    fig.update_layout(**CHART_LAYOUT, height=max(160, 60 * len(labels)))
    fig.update_xaxes(showgrid=True, gridcolor=COLORS["border"], zeroline=False)
    fig.update_yaxes(showgrid=False)
    return fig


def render_analytics() -> None:
    page_header("Analytics", "How RoutingBridge is routing traffic and what it costs.")

    stats = _get("/stats")
    if stats is None:
        return
    if stats["total_requests"] == 0:
        st.markdown('<div class="mp-empty">No requests yet — try the Chat page.</div>', unsafe_allow_html=True)
        return

    c1, c2, c3, c4, c5 = st.columns(5, gap="small")
    c1.markdown(metric_tile("Total Requests", str(stats["total_requests"])), unsafe_allow_html=True)
    c2.markdown(metric_tile("Total Cost", f"${stats['total_cost']:.4f}"), unsafe_allow_html=True)
    c3.markdown(
        metric_tile("Estimated Savings", f"${stats['estimated_savings']:.4f}"), unsafe_allow_html=True
    )
    c4.markdown(metric_tile("Avg Latency", f"{stats['avg_latency_ms']:.0f} ms"), unsafe_allow_html=True)
    quality_label = (
        f"{stats['quality_pass_rate'] * 100:.0f}%" if stats["quality_pass_rate"] is not None else "—"
    )
    c5.markdown(
        metric_tile(f"Quality Pass Rate ({stats['quality_verified_count']} checked)", quality_label),
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)
    col_a, col_b = st.columns(2, gap="medium")
    with col_a:
        st.markdown('<div class="mp-card-title">Requests per Routing Tier</div>', unsafe_allow_html=True)
        tiers = list(stats["requests_per_tier"].keys())
        counts = list(stats["requests_per_tier"].values())
        st.plotly_chart(
            _bar_chart(tiers, counts, COLORS["accent"]),
            use_container_width=True,
            config={"displayModeBar": False},
        )
    with col_b:
        st.markdown('<div class="mp-card-title">Cost per Model</div>', unsafe_allow_html=True)
        models = list(stats["cost_per_model"].keys())
        costs = list(stats["cost_per_model"].values())
        st.plotly_chart(
            _bar_chart(models, costs, COLORS["tier_standard"]),
            use_container_width=True,
            config={"displayModeBar": False},
        )


def render_settings() -> None:
    page_header("Settings", "Current routing configuration — read-only.")
    st.caption(
        "Routing tiers and pricing are defined in config/routing.yaml and "
        "config/pricing.yaml. Changing routing policy is a config edit, not "
        "a runtime write, to avoid file-write race conditions for what is "
        "otherwise a read-only view."
    )

    data = _get("/models")
    if data is None:
        return

    st.markdown("<br>", unsafe_allow_html=True)
    classifier = data["classifier"]
    thresholds = data["confidence_thresholds"]
    rows = "".join(
        [
            kv_row("Classifier Provider", classifier["provider"]),
            kv_row("Classifier Model", classifier["model"]),
            kv_row("Max Output Tokens", str(classifier["max_output_tokens"])),
            kv_row("High Confidence Threshold", f"{thresholds['high']:.2f}"),
            kv_row("Low Confidence Threshold", f"{thresholds['low']:.2f}"),
            kv_row("Escalate on Low Confidence", str(thresholds["escalate_on_low_confidence"])),
        ]
    )
    st.markdown(
        f'<div class="mp-card"><div class="mp-card-title">Classifier</div>{rows}</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div class="mp-card-title" style="margin-top:24px;">Routing Tiers</div>', unsafe_allow_html=True)
    cols = st.columns(3, gap="medium")
    for col, (tier_name, tier) in zip(cols, data["tiers"].items()):
        rows = "".join(
            [
                kv_row("Provider", tier["provider"]),
                kv_row("Model", tier["model"]),
                kv_row("Max Output Tokens", str(tier["max_output_tokens"])),
                kv_row("Input $/1M", f"${tier['input_per_million']}"),
                kv_row("Output $/1M", f"${tier['output_per_million']}"),
            ]
        )
        reasons = "".join(f"<li style='margin-bottom:4px;'>{r}</li>" for r in tier["reasons"])
        with col:
            st.markdown(
                f'<div class="mp-card">'
                f'<div style="margin-bottom:12px;">{tier_badge(tier_name.upper())}</div>'
                f"{rows}"
                f'<div style="margin-top:12px; font-size:13px; color:{COLORS["text_muted"]};">'
                f'<ul style="padding-left:18px; margin:0;">{reasons}</ul></div>'
                f"</div>",
                unsafe_allow_html=True,
            )


PAGES = {
    "Chat": render_chat,
    "History": render_history,
    "Analytics": render_analytics,
    "Settings": render_settings,
}

with st.sidebar:
    st.markdown(
        '<div style="font-size:19px; font-weight:600; letter-spacing:-0.01em; '
        'margin-bottom:2px;">RoutingBridge</div>'
        f'<div style="font-size:12.5px; color:{COLORS["text_muted"]}; margin-bottom:24px;">'
        "Multi-LLM Routing</div>",
        unsafe_allow_html=True,
    )
    selected_page = st.radio("Navigate", list(PAGES.keys()), label_visibility="collapsed")

PAGES[selected_page]()
