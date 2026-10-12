# LLM providers

The AI search (`src/navigator/app/assistant.py`) talks to the **Responses API** through the official OpenAI SDK: flat strict
function tools, `instructions`, `parallel_tool_calls=false`, `function_call_output` follow-ups and a final `text.format` of type
`json_schema` (strict). It is configured in `.env`: `LLM_ENABLED`, `OPENAI_MODEL`, `OPENAI_API_KEY` and, for an OpenAI-compatible
provider, `OPENAI_BASE_URL`. `python -m navigator.cli app status` shows what is configured (the key is never printed).

What the assistant guarantees does not depend on the provider: the model can only pick IDs that a tool returned in the same
request, every card fact is read back from the database (never from the model's text), `reason_codes` come from a fixed list of
five, and e-mail addresses or document numbers are refused before any call is made.

## DeepSeek, verified on 2026-10-10

Base URL `https://api.deepseek.com/v1`, model `deepseek-chat`, with the project's own key. The probes are
`scripts/probe_deepseek.py` and `scripts/probe_deepseek_tools.py`; they read `OPENAI_API_KEY` from the environment and print no key.

| check | result |
| --- | --- |
| `POST /responses`, plain request | completed |
| `POST /chat/completions`, plain request | works (the assistant does not use it) |
| Responses, round 1: strict function tool + `instructions` + `parallel_tool_calls=false` | completed; output items `message` and `function_call`, valid JSON arguments, a `call_id` |
| Responses, round 2: `function_call_output` follow-up + `text.format` json_schema (strict) | completed; one JSON object in the requested shape |
| `deepseek-reasoner`, 16 output tokens | `incomplete` (Responses) and `length` (chat): not usable at that budget, not tried further |

One result of the first probe is not a limitation: the chat-completions request with tools and `json_object` answered HTTP 400 only
because the probe's prompt did not contain the word "json".

**Through the real assistant** (`serve --mode live`, the 58 records published at the time, five conversations in all; on 2026-10-11 one natural-language search was re-checked through the real model on the 529 records by `node tests/e2e/site.mjs --ai`):

* *search* "a Métis student in BC looking for training support", *analysis* "compare national and regional coverage" and *match*
  "a First Nations student at SFU, full-time undergraduate" all came back as valid structured answers with grounded IDs. No request
  was rejected as `INVALID_MODEL_OUTPUT` or `UNGROUNDED_RESPONSE`.
* The first round exposed two defects of ours, not of the provider; both are fixed with tests. Every record was published as
  `postsecondary` only, so a `training` goal could not match: the search needed four tool calls and its first returned nothing
  (we infer the cause; after the fix the same request takes two calls and returns the two records whose titles name training or
  trades). And an *analysis* answer reported only the last of several statistics calls; it now reports every slice.

What this does not show: behaviour under rate limits or quota errors, long conversations (up to 10 history messages), many users
at once, or Chinese input (the instructions allow it; only English was tried). The probe's own schema had no `enum`, and the model
chose its own `reason_codes`; the real schema restricts them to five values and the prompt lists them. If a provider ever returns
another value the answer is rejected (`INVALID_MODEL_OUTPUT`, "The answer could not be safely verified. Please retry."), never shown.

## Checking another provider

1. Put its base URL, model and key in `.env` (`OPENAI_BASE_URL`, `OPENAI_MODEL`, `OPENAI_API_KEY`, `LLM_ENABLED=true`).
2. Run the two probes (copy the key into the environment of that shell first); the second one exercises exactly what the assistant
   uses. A provider that only offers chat completions would need a second adapter in `assistant.py`.
3. `python -m navigator.cli serve --mode live`, then `POST /api/conversation` with `{"mode": "search", "message": "..."}` and read
   `tools_used`, `results` and any `error.code`.
