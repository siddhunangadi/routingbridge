# Production stabilization notes

A live verification pass against the real deployed Supabase database
surfaced issues that only show up when the app actually runs against a
real API and a real database, not just against mocked tests. All of the
following are fixed and re-verified live, not just covered by unit tests.

## The OpenRouter classifier and quality verifier were silently dead in production

Mistral (via OpenRouter) wraps its JSON reply in a ` ```json ` markdown
fence unless explicitly told not to; `OpenRouterProvider.generate()`
never requested `response_format: json_object` (the Gemini path did,
before the OpenRouter migration, and that request was lost in the move).
Every real classifier call failed to parse and silently fell back to the
word-count heuristic — `classify_heuristically`'s graceful degradation
worked exactly as designed, which is precisely why nobody noticed the
primary path was never running.

Fixed: `LLMProvider.generate()` now takes an optional `response_format`
parameter, requested by the classifier and quality verifier only (never
for regular chat answers); a defensive markdown-fence strip was also
added as a second line of defense. Verified live against the real
OpenRouter API: `task_type` is now populated with real labels (`"Math"`,
`"CodeGen"`, `"Q&A"`, ...), `classifier_model` no longer reads
`"heuristic"` on a healthy request, and `quality_results` now receives
real rows with real pass/fail verdicts.

## The History page crashed the entire Streamlit process (SIGSEGV) on a clean install

Root-caused with `PYTHONFAULTHANDLER=1` (not assumed): a fresh
`pip install -r requirements.txt` resolved `numpy==2.4.6` against the
pinned `pandas==2.2.3`, and that combination segfaults inside pyarrow's
internal `pandas_compat.convert_column` — the exact path `st.dataframe()`
uses, not the public `pa.Table.from_pandas()` API (which does *not*
crash, which is why an initial pandas/pyarrow smoke test looked fine).

Fixed by pinning `numpy==1.26.4` and `pyarrow==17.0.0` — versions
actually exercised together at `streamlit==1.39.0`'s release. Verified on
a from-scratch venv: History renders correctly and survives repeated
navigation.

## The Streamlit chat request timeout (30s) was incompatible with the ADVANCED tier's real latency (~140s for DeepSeek R1)

A slow-but-alive backend response was indistinguishable from a Render
cold start, so the UI's retry logic would silently resubmit the same
prompt — a real duplicate-billing risk on a paid LLM call.

Fixed: the `/chat` request now uses a configurable timeout
(`CHAT_TIMEOUT_SECONDS`, default 180s) and does not retry on a genuine
timeout (cold-start placeholder pages return near-instantly; a real
timeout at 180s is never a cold start). A spinner now covers the wait.
Verified live: an ADVANCED-tier prompt completes through the actual UI
with exactly one upstream request, no duplicate.

## Row Level Security was disabled on every table in the live Supabase project

This exposed all prompts/responses/audit data to the `anon` role. The
app never uses Supabase's client SDK or the anon key anywhere — it
connects directly to Postgres via a `postgresql+psycopg://` URL as the
`postgres` role, which bypasses RLS entirely regardless of policy.

Fixed: RLS is now enabled on all 9 tables with **zero permissive
policies**, denying `anon`/`authenticated` access completely. This is
the correct end state for this app, not a placeholder: nothing should
ever read or write these tables except the backend's own direct
connection. Verified live: full `/chat` (write) and `/history` (read)
functionality intact after enabling RLS.

## An orphaned `alembic_version` table existed in the live database

This existed despite zero Alembic files anywhere in this repo, directly
contradicting the README's "no separate migration framework" claim.
Dropped — it was leftover cruft from an earlier experiment, never read
or written by any code here.
