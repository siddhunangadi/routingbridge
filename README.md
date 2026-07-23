<div align="center">

# 🧭 RoutingBridge

### Stop sending every question to your most expensive model.

**One chat endpoint. Two AI providers, three routing tiers. Every prompt automatically judged for difficulty and routed to the cheapest model that can actually answer it well.**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](requirements.txt)
[![License](https://img.shields.io/badge/license-MIT-green)](#license)
[![Live Demo](https://img.shields.io/badge/demo-live-brightgreen)](https://routingbridge-frontend.onrender.com)

### 🔗 [**Try the live demo →**](https://routingbridge-frontend.onrender.com)

[Why this exists](#why-this-exists) • [What it does](#what-it-does-for-you) • [See it live](#see-it-live-in-5-minutes) • [How it works](#how-it-works)

</div>

---

## Why this exists

Most apps that call an LLM pick one model and use it for everything —
"What's 9 times 6?" and "explain the tradeoffs between Raft and Paxos"
both hit the same expensive model, even though the first one is
answerable by something 10-50x cheaper.

**RoutingBridge makes that decision automatically, on every request.**
A small, fast model looks at your prompt first, judges how hard it
actually is, and hands it off to the cheapest model that can do it
justice. You get one endpoint to call. It gets you a full explanation
of why it picked what it picked — and exactly what it cost.

## What it does for you

- 💸 **Cuts your model spend automatically** — simple prompts go to a
  fast, cheap model; hard prompts get escalated to a stronger one.
  No manual model-picking, no defaulting to the expensive option.
- 🧠 **Judges difficulty with a real LLM, not keyword rules** — a
  lightweight classifier reads the prompt and returns a structured
  verdict: routing tier, task type, reasoning level, and a confidence
  score — not a guess based on word count.
- 🛟 **Never goes down because the classifier does** — if the classifier
  call fails for any reason, a heuristic fallback keeps the app
  answering instead of erroring out, and it's flagged in the response
  so you can see exactly when it happened.
- 🎯 **Escalates when it's not sure** — low-confidence classifications
  automatically bump up one tier, trading a little cost for a lot more
  safety on prompts the classifier is unsure about.
- 🧭 **Explains every routing decision** — each response comes with the
  tier, provider, model, confidence, and a plain-English reason list,
  not a black-box model name.
- 📊 **Shows you exactly where your money goes** — the dashboard tracks
  total requests, total cost, average latency, cost per model, and
  estimated savings versus always using the most expensive tier.
- 🔌 **Works with the providers you can actually get keys for** —
  native Google Gemini plus OpenRouter, which alone unlocks Mistral,
  DeepSeek, Qwen, Llama and more through one gateway.
- ⚙️ **Routing policy lives in config, not code** — which model serves
  which tier, and how it's priced, is one YAML edit away — no
  redeploy required to change routing behavior.

## See it live in 5 minutes

You don't need to read any code to try this.

```bash
# 1. Get the project
git clone https://github.com/siddhunangadi/routingbridge.git
cd routingbridge

# 2. Install dependencies
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Add your provider keys
cp .env.example .env
# open .env and paste in GOOGLE_API_KEY and OPENROUTER_API_KEY

# 4. Start both services
uvicorn backend.main:app --reload &
streamlit run frontend/streamlit_app.py
```

Now open **http://localhost:8501** — that's the full UI: chat,
request history, analytics dashboard, and routing config, all in one
place.

Or just ask it something directly:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explain why the sky is blue."}'
```

It responds with the answer **and** a full explanation of why it
chose the model it did:

```json
{
  "response": "The sky appears blue because...",
  "routing_tier": "BASIC",
  "provider": "google",
  "model": "gemini-2.5-flash",
  "confidence": 0.97,
  "routing_reason": [
    "Simple, short prompt",
    "Low reasoning complexity",
    "Fast, cheap model is sufficient"
  ],
  "total_cost": 0.000213,
  "total_latency_ms": 3120
}
```

> **Heads up:** the live demo runs on free-tier hosting, which sleeps
> after 15 minutes of inactivity. The first request after a while can
> take up to a minute to wake back up — the UI shows a friendly
> "starting up" message and retries automatically instead of erroring.

## How it works

```
your prompt
    │
    ▼
┌───────────────────────┐   "how hard is this, really?"
│  Routing classifier    │    (Gemini 2.5 Flash, structured JSON output,
│  (+ heuristic fallback)│     falls back to word-count if it fails)
└───────────────────────┘
    │
    ▼
┌───────────────────────┐   "given the tier and confidence, which
│    Routing engine      │    provider/model actually handles this?"
└───────────────────────┘   (escalates one tier up if confidence is low)
    │
    ▼
┌───────────────────────┐   Gemini for the fast tier, OpenRouter
│  Provider + generation │   (Mistral / DeepSeek) for the rest
└───────────────────────┘
    │
    ▼
┌───────────────────────┐   real token counts × config-driven
│    Cost estimator      │    pricing — not an estimate
└───────────────────────┘
    │
    ▼
   your answer, plus the full reasoning trail, cost, and latency —
   logged to history and rolled up into the analytics dashboard
```

Nothing above is a black box — every decision is visible in the
response and in the "Why this model was selected" panel in the UI.

## What's under the hood (for the technical reader)

- **FastAPI** backend, **Streamlit** frontend, **SQLite** for
  persistence
- A one-method provider interface (`LLMProvider`) behind which native
  Gemini and OpenRouter both live — adding a third provider is one
  new class and one config entry, not a rewrite
- Routing tiers, provider/model mapping, and pricing all live in
  `config/routing.yaml` and `config/pricing.yaml`
- Confidence-based tier escalation, with the escalation reason
  attached to the response so it's never a silent decision
- Defensive classifier design: any LLM failure — auth, rate limit,
  malformed output — degrades to a heuristic instead of a 500
- Deployed on Render as two independent services (backend + frontend),
  wired together over HTTP

## Run with Docker

```bash
docker compose up --build
```

Starts both services — backend on `:8000`, frontend on `:8501` — with
SQLite data persisted in a mounted volume.

## License

MIT — use it, fork it, ship it.
