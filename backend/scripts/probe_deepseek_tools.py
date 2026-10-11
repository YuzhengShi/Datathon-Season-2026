"""Probe round 2: verify the exact Responses-API features assistant.py relies on.

1. tools (flat function format, strict) + instructions + parallel_tool_calls=False
2. function_call output items with call_id/arguments
3. function_call_output follow-up round
4. text.format json_schema strict structured final answer
"""

import json
import os
import sys

from openai import APIStatusError, OpenAI

KEY = os.environ["OPENAI_API_KEY"]
MODEL = "deepseek-chat"
SEARCH_TOOL = {
    "type": "function",
    "name": "search_opportunities",
    "description": "Search funding records with typed filters.",
    "parameters": {
        "type": "object",
        "properties": {
            "filters": {
                "type": "object",
                "properties": {"provinces": {"type": "array", "items": {"type": "string"}}},
                "required": ["provinces"],
                "additionalProperties": False,
            },
            "limit": {"type": "integer"},
            "offset": {"type": "integer"},
        },
        "required": ["filters", "limit", "offset"],
        "additionalProperties": False,
    },
    "strict": True,
}
DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent_summary": {"type": "string"},
        "question": {"type": ["string", "null"]},
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "opportunity_id": {"type": "string"},
                    "reason_codes": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["opportunity_id", "reason_codes"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["intent_summary", "question", "recommendations"],
    "additionalProperties": False,
}


def client():
    return OpenAI(api_key=KEY, base_url="https://api.deepseek.com/v1", timeout=60, max_retries=0)


def round_one(api, structured=True):
    kwargs = {
        "model": MODEL,
        "instructions": "You are a funding assistant. Always call a data tool before recommending anything.",
        "input": [
            {"role": "user", "content": "I am a Métis student in BC looking for training support"}
        ],
        "tools": [SEARCH_TOOL],
        "parallel_tool_calls": False,
        "max_output_tokens": 1800,
        "store": False,
    }
    if structured:
        kwargs["text"] = {
            "format": {
                "type": "json_schema",
                "name": "funding_answer",
                "schema": DRAFT_SCHEMA,
                "strict": True,
            }
        }
    return kwargs, api.responses.create(**kwargs)


def main():
    api = client()
    try:
        kwargs, response = round_one(api)
    except APIStatusError as exc:
        print("round1 with text.format failed:", exc.status_code, str(exc)[:300])
        print("retrying without text.format…")
        kwargs, response = round_one(api, structured=False)
    types = [item.type for item in response.output]
    print("round1 status:", response.status, "output types:", types)
    calls = [item for item in response.output if item.type == "function_call"]
    if not calls:
        print("round1 text:", response.output_text[:400])
        return 1
    call = calls[0]
    print("function_call:", call.name, "call_id:", call.call_id, "arguments:", call.arguments[:200])
    # follow-up round with the tool output
    result = {
        "data_mode": "demo",
        "total": 2,
        "records": [
            {"id": "mnbc", "title": "MNBC STEPS", "amount": None},
            {"id": "nutrien", "title": "Nutrien Indigenous Youth Awards", "amount": "5000.00"},
        ],
    }
    inputs = kwargs["input"] + [item.model_dump(exclude_none=True) for item in response.output]
    inputs.append(
        {
            "type": "function_call_output",
            "call_id": call.call_id,
            "output": json.dumps(result),
        }
    )
    final = api.responses.create(
        model=MODEL,
        instructions=kwargs["instructions"],
        input=inputs,
        tools=[SEARCH_TOOL],
        parallel_tool_calls=False,
        max_output_tokens=1800,
        store=False,
        text={
            "format": {
                "type": "json_schema",
                "name": "funding_answer",
                "schema": DRAFT_SCHEMA,
                "strict": True,
            }
        },
    )
    print("round2 status:", final.status, "output types:", [item.type for item in final.output])
    print("round2 output_text:", final.output_text[:600])
    return 0


if __name__ == "__main__":
    sys.exit(main())
