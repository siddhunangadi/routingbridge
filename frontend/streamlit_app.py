"""ModelPilot Streamlit UI.

One file, sidebar radio for navigation between four pages. No multipage
framework, no page-router abstraction — for four screens that each just
call one backend endpoint and render it, a single file with four small
functions is the whole solution.
"""

import os

import httpx
import pandas as pd
import streamlit as st

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="ModelPilot", page_icon="🧭", layout="wide")


def _get(path: str, **params) -> dict | list | None:
    try:
        resp = httpx.get(f"{BACKEND_URL}{path}", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        st.error(f"Could not reach backend at {BACKEND_URL}{path}: {exc}")
        return None


def render_chat() -> None:
    st.title("🧭 ModelPilot Chat")
    st.caption("Every prompt is routed to the cheapest model that can handle it.")

    prompt = st.text_area("Enter your prompt", height=120, placeholder="Ask anything...")
    if st.button("Send", type="primary") and prompt.strip():
        with st.spinner("Classifying and routing..."):
            try:
                resp = httpx.post(f"{BACKEND_URL}/chat", json={"prompt": prompt}, timeout=60)
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = exc.response.json().get("detail", str(exc))
                st.error(f"Request failed: {detail}")
                return
            except httpx.HTTPError as exc:
                st.error(f"Could not reach backend: {exc}")
                return

        data = resp.json()
        st.markdown("### Response")
        st.write(data["response"])

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Model", data["model"])
        c2.metric("Routing Tier", data["routing_tier"])
        c3.metric("Total Cost", f"${data['total_cost']:.6f}")
        c4.metric("Latency", f"{data['total_latency_ms']:.0f} ms")

        with st.expander("Why this model was selected", expanded=True):
            for reason in data["routing_reason"]:
                st.write(f"- {reason}")
            if data["escalated"]:
                st.info(
                    f"Escalated from {data['original_tier']} tier due to low "
                    f"classifier confidence ({data['confidence']:.2f})."
                )
            fallback_note = " (fallback heuristic used)" if data["fallback_used"] else ""
            st.caption(
                f"Task type: {data['task_type']} · Reasoning level: {data['reasoning_level']} "
                f"· Classifier: {data['classifier_model']}{fallback_note}"
            )


def render_history() -> None:
    st.title("📜 Request History")
    rows = _get("/history", limit=100)
    if rows is None:
        return
    if not rows:
        st.info("No requests yet — try the Chat page.")
        return

    df = pd.DataFrame(rows)
    df = df[
        [
            "timestamp",
            "prompt",
            "routing_tier",
            "escalated",
            "provider",
            "model",
            "total_cost",
            "total_latency_ms",
            "fallback_used",
        ]
    ]
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_analytics() -> None:
    st.title("📊 Analytics Dashboard")
    stats = _get("/stats")
    if stats is None:
        return
    if stats["total_requests"] == 0:
        st.info("No requests yet — try the Chat page.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Requests", stats["total_requests"])
    c2.metric("Total Cost", f"${stats['total_cost']:.4f}")
    c3.metric("Avg Latency", f"{stats['avg_latency_ms']:.0f} ms")
    c4.metric("Estimated Savings", f"${stats['estimated_savings']:.4f}")

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Requests per Routing Tier")
        tier_df = pd.DataFrame(
            list(stats["requests_per_tier"].items()), columns=["Tier", "Requests"]
        ).set_index("Tier")
        st.bar_chart(tier_df)
    with col_b:
        st.subheader("Cost per Model")
        cost_df = pd.DataFrame(
            list(stats["cost_per_model"].items()), columns=["Model", "Cost"]
        ).set_index("Model")
        st.bar_chart(cost_df)


def render_settings() -> None:
    st.title("⚙️ Settings")
    st.caption(
        "Routing tiers and pricing are defined in config/routing.yaml and "
        "config/pricing.yaml, not editable from this UI — changing routing "
        "policy is a config edit, not a runtime write, to avoid file-write "
        "race conditions for what is otherwise a read-only view."
    )
    data = _get("/models")
    if data is None:
        return

    st.subheader("Classifier")
    st.json(data["classifier"])

    st.subheader("Confidence Thresholds")
    st.json(data["confidence_thresholds"])

    st.subheader("Routing Tiers")
    for tier_name, tier in data["tiers"].items():
        with st.expander(tier_name.upper(), expanded=True):
            st.write(f"**Provider:** {tier['provider']}  ·  **Model:** {tier['model']}")
            st.write(
                f"**Pricing:** ${tier['input_per_million']}/1M input tokens, "
                f"${tier['output_per_million']}/1M output tokens"
            )
            st.write("**Reasons this tier is chosen:**")
            for reason in tier["reasons"]:
                st.write(f"- {reason}")


PAGES = {
    "Chat": render_chat,
    "History": render_history,
    "Analytics": render_analytics,
    "Settings": render_settings,
}

st.sidebar.title("ModelPilot")
selected_page = st.sidebar.radio("Navigate", list(PAGES.keys()))
PAGES[selected_page]()
