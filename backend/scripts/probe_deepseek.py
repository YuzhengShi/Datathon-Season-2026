"""One-off probe: does the configured DeepSeek endpoint support /responses, /chat/completions, both?

Run: .venv/Scripts/python scripts/probe_deepseek.py
Reads OPENAI_API_KEY from the environment; prints only capability booleans, never the key.
"""

import os
import sys

from openai import APIStatusError, OpenAI

KEY = os.environ["OPENAI_API_KEY"]
MODELS = ["deepseek-chat", "deepseek-reasoner"]


def try_responses(client, model):
    response = client.responses.create(
        model=model,
        input=[{"role": "user", "content": "Reply with the single word: pong"}],
        max_output_tokens=16,
        store=False,
    )
    return response.status, response.output_text


def try_chat(client, model):
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Reply with the single word: pong"}],
        max_tokens=16,
    )
    return response.choices[0].finish_reason, response.choices[0].message.content


def try_chat_tools(client, model):
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Find scholarships in BC"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "search_opportunities",
                    "description": "Search funding records.",
                    "parameters": {
                        "type": "object",
                        "properties": {"provinces": {"type": "array", "items": {"type": "string"}}},
                        "required": ["provinces"],
                        "additionalProperties": False,
                    },
                },
            }
        ],
        response_format={"type": "json_object"},
        max_tokens=200,
    )
    choice = response.choices[0]
    calls = [
        {"name": c.function.name, "arguments": c.function.arguments}
        for c in (choice.message.tool_calls or [])
    ]
    return choice.finish_reason, calls, choice.message.content


def main():
    for base in ("https://api.deepseek.com/v1",):
        client = OpenAI(api_key=KEY, base_url=base, timeout=30, max_retries=0)
        for model in MODELS:
            print(f"base={base} model={model}")
            try:
                print("  responses:", try_responses(client, model))
            except APIStatusError as exc:
                print(f"  responses: HTTP {exc.status_code} {str(exc)[:120]}")
            except Exception as exc:  # noqa: BLE001 - probe reports everything
                print(f"  responses: {type(exc).__name__} {str(exc)[:120]}")
            try:
                print("  chat:", try_chat(client, model))
            except APIStatusError as exc:
                print(f"  chat: HTTP {exc.status_code} {str(exc)[:120]}")
            except Exception as exc:  # noqa: BLE001
                print(f"  chat: {type(exc).__name__} {str(exc)[:120]}")
            if model == "deepseek-chat":
                try:
                    print("  chat+tools+json_object:", try_chat_tools(client, model))
                except APIStatusError as exc:
                    print(f"  chat+tools: HTTP {exc.status_code} {str(exc)[:120]}")
                except Exception as exc:  # noqa: BLE001
                    print(f"  chat+tools: {type(exc).__name__} {str(exc)[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
