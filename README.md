# ModelPilot — Intelligent Multi-LLM Routing & Cost Optimization Platform

Routes each prompt to the cheapest LLM capable of handling it, instead of
always calling the most expensive model. Built as a portfolio project.

## Status
Phase 1 complete: project skeleton, environment config, FastAPI app with
`/health`. More phases in progress — see commit history.

## Setup
```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in provider API keys
uvicorn backend.main:app --reload
```
