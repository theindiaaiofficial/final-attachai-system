# RAG-2.0 local debugging guide

## Enable safe trace logging

Set these values in the local process environment or `.env` without committing the file. Do not print the environment or credential values.

```text
ORBIT_TRACE_DEBUG=1
ORBIT_TRACE_INCLUDE_CONTENT=0
ORBIT_TRACE_LOG_PATH=data/logs/orbit-trace.jsonl
ORBIT_TRACE_MAX_BYTES=5000000
```

`ORBIT_TRACE_INCLUDE_CONTENT=1` is honored only outside production. Default traces contain lengths, hashes/identifiers where useful, stage metadata, provider/model names, route decisions, similarities, source IDs, durations, and error types; they do not contain authorization headers or API keys. The trace file is JSONL and rotates to `.1` at the configured size.

## Run locally

From `orbit-ai-python-final/orbit-ai-python-final`:

```powershell
python -m compileall -q app tests scripts
ruff check app tests scripts
pytest -q
uvicorn app.main:app --host 127.0.0.1 --port 10000
```

Use the existing configured provider settings at runtime. Do not replace credentials for debugging. Check `GET /health` and `GET /ready`, then use the client widget with its existing tenant API key.

## Regression questions

Run these in one fresh widget session for the configured AttachAI tenant:

1. `aap koun ho`
2. `what is your name`
3. `are you ChatGPT?`
4. `who is this AttachAI`
5. `What does AttachAI Assistant do?`
6. Ask a clearly unsupported business question and confirm the answer says the information is unavailable rather than inventing it.
7. If the assistant asks the business/general clarification, reply `business` and confirm it continues the original question instead of repeating the clarification.
8. Ask a follow-up such as `How much does it cost?` after a documented service question and confirm history is sent to the router.

## Trace event order

For each request, inspect records sharing the response `request_id`/`trace_id`. Expected stages are:

`request → identity → history → query → router → retrieval → evidence → answer → grounding → correction (when needed) → persistence → final_response`

General identity turns intentionally omit retrieval/evidence/grounding. A business turn should include tenant filtering, retrieved source IDs, evidence status, supported source IDs, citation IDs, and whether the single correction cycle ran. Errors include an exception type and the failing stage without exposing secrets.
