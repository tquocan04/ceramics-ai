# Ceramics AI Service

Natural-language order extraction for the ceramics manufacturing pipeline.

A customer writes an order the way they'd say it out loud:

> Gấp: 350 đĩa gốm men nâu họa tiết chim hạc cao 4cm, nung 1300°C, cần xong trong 7 ngày.

This service turns that into typed, validated, evidence-backed data the workshop can act on — and, just as importantly, leaves `null` everything the customer never said.

**This service interprets language. It does not own manufacturing state.** It has no database, writes nothing, and cannot advance a workflow. Its output is a proposal a human reviews before anything is created.

---

## Quick start

```powershell
# 1. install
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 2. configure
Copy-Item .env.example .env      # then set AI_API_KEY

# 3. run the offline test suite - no API key or network needed
.\.venv\Scripts\python.exe -m pytest

# 4. start
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8100
```

Interactive docs at <http://127.0.0.1:8100/docs>.

No API key to hand? Set `AI_PROVIDER=fake` and `/health` plus every error path still work.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness. Unauthenticated, never calls the provider. |
| `POST` | `/v1/orders/extract` | Extract structured order data from free text. |

```powershell
curl.exe -X POST http://127.0.0.1:8100/v1/orders/extract `
  -H "Content-Type: application/json" `
  --data-raw '{\"description\":\"Gấp: 350 đĩa gốm men nâu họa tiết chim hạc cao 4cm, nung 1300°C, cần xong trong 7 ngày.\",\"language\":\"vi\"}'
```

```jsonc
{
  "schema_version": "1.0",
  "prompt_version": "order-extraction-v1",
  "provider": "openai-compatible",
  "model": "openai/gpt-4o-mini",

  "extracted": {
    "product_name": "Đĩa gốm", "quantity": 350,
    "height_cm": 4.0, "width_cm": null,
    "decoration_pattern": "Chim hạc", "glaze_type": "Men nâu",
    "firing_temperature_c": 1300, "deadline_days": 7
  },
  "estimated": { "clay_kg": 36.0, "glaze_kg": 2.4, "firing_duration_hours": 10.5 },

  "priority": "URGENT",
  "priority_reason": "Số lượng 350 sản phẩm với deadline 7 ngày — cần ưu tiên tối đa",
  "provenance": { "quantity": [5, 8], "height_cm": [42, 49] },

  "evidence": { "quantity": "350", "height_cm": "cao 4cm" },
  "ai_priority": "URGENT",
  "ai_priority_reason": "Số lượng lớn với thời hạn ngắn.",
  "missing_fields": ["width_cm"],
  "warnings": [],
  "metadata": { "latency_ms": 1840, "attempts": 1, "usage": { "input_tokens": 812 } }
}
```

`extracted`, `estimated`, `priority`, `priority_reason` and `provenance` together are exactly the frontend's `AIAnalysisResult` — the backend picks those five keys and hands them to the review screen with no mapping code.

---

## How it works

The LLM does one job: read Vietnamese and quote its sources. Everything else is deterministic Python.

```
description
    ↓  LLM             typed fields + a verbatim quote per field
    ↓  normalise       mm→cm, "một tuần"→7, "1.280°C"→1280
    ↓  resolve spans   quotes → character offsets
    ↓  validate        impossible values dropped, odd ones flagged
    ↓  estimate        clay/glaze/firing from formulas, not the model
    ↓  prioritise      business rule; the model's opinion kept alongside
OrderAnalysisResponse
```

Three decisions are worth knowing about:

**The model never returns character offsets.** Counting characters is what language models are worst at, and a wrong offset draws a visibly wrong highlight. It quotes text instead; `spans.py` locates the quote through four escalating strategies (exact → case-insensitive → whitespace-tolerant → diacritic-insensitive with an index map). If all four fail the field is simply omitted from `provenance` with a warning. **A missing highlight is cosmetic; a fabricated one is a bug.**

**Estimates are arithmetic, not opinion.** Clay mass is a function of quantity and height. Asking a model would produce a different answer every call for something we can compute exactly. The constants live in `.env`, so the workshop can recalibrate without a deploy.

**A null is a result, not a gap.** For *"Làm khoảng vài trăm cái, càng sớm càng tốt"* the correct answer is `quantity: null` plus a warning — not a plausible-looking 200. The regression suite asserts this on 29 separate fields.

### Warnings vs. errors

A warning never fails the request. `firing_temperature_c: 3000` is kept and flagged, because a specialist kiln might genuinely sit outside our defaults and the manager knows the workshop better than the rule does. Only impossible values (`quantity <= 0`) are dropped to null, so nothing downstream is estimated from nonsense.

---

## Configuration

Everything is read from `.env` via `pydantic-settings`, validated at startup — a missing key fails the boot, not the first customer request. See `.env.example` for the full list.

`AI_PROVIDER=openai-compatible` works against any OpenAI-shaped endpoint; pick one with `AI_BASE_URL`:

| Provider | `AI_BASE_URL` | `AI_MODEL` |
|---|---|---|
| OpenRouter | `https://openrouter.ai/api/v1` | `openai/gpt-4o-mini` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Ollama (local) | `http://localhost:11434/v1` | `qwen2.5:14b` |

### Timeouts and retries

Three numbers, because there are three units of work: `AI_TIMEOUT_SECONDS` (30) bounds one HTTP round-trip, `AI_ATTEMPT_SECONDS` (35) bounds one agent run — which may contain `1 + AI_OUTPUT_RETRIES` round-trips — and `AI_REQUEST_BUDGET_SECONDS` (45) bounds the whole request. Startup warns if the budget cannot fit the retries you asked for.

Retries are split by *what failed*:

| layer | handles | cost |
|---|---|---|
| `AI_OUTPUT_RETRIES` (pydantic-ai) | output that will not parse or validate — retried **in-conversation**, with the error shown to the model | one short completion |
| `AI_MAX_RETRIES` (tenacity) | the call never completed: timeout, 429, 5xx, connection | a whole fresh inference |

The rule: the transport layer may only retry faults carrying no information the model could act on. If the model spoke, tenacity is done. Getting this backwards is what turned one bad response into three 31-second inferences.

`AI_REASONING` (`off` | `minimal` | `low` | `medium` | `high` | `default`) controls reasoning tokens — the largest latency term on a reasoning model, and worth nothing for extraction. `off` is demoted to `minimal` automatically on endpoints that reason unconditionally.

### Errors

Every failure returns the same envelope the frontend already parses:

```json
{ "error": { "code": "AI_TIMEOUT", "message": "AI không phản hồi kịp thời.", "details": null } }
```

| Code | HTTP | |
|---|---|---|
| `EMPTY_DESCRIPTION`, `DESCRIPTION_TOO_LONG`, `VALIDATION_FAILED` | 400 | |
| `UNAUTHORIZED` | 401 | bad `X-Internal-API-Key` |
| `AI_SCHEMA_VALIDATION_FAILED` | 422 | model output broke the schema |
| `AI_RATE_LIMITED` | 429 | |
| `AI_PROVIDER_ERROR`, `AI_INVALID_JSON` | 502 | |
| `AI_PROVIDER_UNAVAILABLE` | 503 | |
| `AI_TIMEOUT` | 504 | |

The first four names are shared verbatim with `frontend/lib/domain/errors.ts`, so the backend needs no translation table.

### Authentication

Set `INTERNAL_API_KEY` and every `/v1` route requires a matching `X-Internal-API-Key` header (`/health` stays open). Leave it empty and the check is skipped — local development needs no header. The public frontend should never call this service directly.

---

## Testing

```powershell
.\.venv\Scripts\python.exe -m pytest          # offline; excludes `live`
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
```

131 tests, no network, no API key.

### The regression suite

`tests/fixtures/order_extraction_cases.json` holds 30 golden cases covering spelled-out numerals, unit variants, deadline phrasings, missing fields, ambiguous input, mixed Vietnamese/English, conversational noise, and a prompt-injection attempt. It runs in two modes:

**replay** (default, offline) drives recorded model output through the real post-LLM pipeline. It cannot tell you whether the model reads Vietnamese well, but it catches the day someone changes a formula, a threshold or a span rule. It must score 100%.

**live** runs the same cases against the real provider — this is where extraction accuracy is actually measured:

```powershell
$env:RUN_AI_INTEGRATION_TESTS=1
.\.venv\Scripts\python.exe -m pytest -m live
```

Both print a per-field accuracy table and write `tests/regression/report.json`. Scoring is per-field: numerics and enums exact, free text compared diacritic- and case-insensitively against a per-case `accept` list, and **null expectations exact** — that last one is the anti-hallucination check.

After changing the prompt or the model, re-record and read the diff — it is the clearest view of what your change actually did:

```powershell
$env:RUN_AI_INTEGRATION_TESTS=1
.\.venv\Scripts\python.exe -m tests.regression.record_live
```

---

## Layout

```
src/app/
├── main.py config.py dependencies.py exceptions.py logging.py
├── api/v1/          health.py  order_analysis.py
├── llm/             provider.py (Protocol)  client.py (real + fake)  errors.py
├── features/order_extraction/
│                    schemas.py  prompt.py  service.py
│                    normalizer.py  spans.py  validators.py
│                    estimator.py  priority.py
├── prompts/         registry.py  versions.py
└── common/          enums.py  responses.py  retry.py
```

`llm/provider.py` defines a one-method `Protocol`. PydanticAI already abstracts over vendors, but it still performs real I/O — feature code written against it can only be tested with a network call. The narrower Protocol makes `FakeProvider` a few dozen lines and lets the whole suite run offline.

---

## Status

Implements **AI-000 → AI-080** of `ceramics-ai-project-plan.md`.

Not yet built: the command interpreter (AI-090 → AI-110), main-backend integration (AI-120+), Telegram, and read-only tool calling. `src/app/features/command_interpreter/` exists as an empty seam.

### Two deliberate deviations from the plan

Both are places the markdown was written without the frontend code in view:

1. **§10's nested shape was not used.** The plan nests `dimensions.{height_cm,width_cm,diameter_cm}` and names the field `pattern`. The frontend's `AIExtractedData` is flat, calls it `decoration_pattern`, and has no `diameter_cm` — Vietnamese *"đường kính"* maps onto `width_cm`. The service returns the frontend's shape so integration needs no adapter.
2. **§11 marks character spans P1; they are P0 here.** `AIAnalysisResult.provenance` already drives highlight rendering in the existing review screen. Deferring spans would break working UI.
