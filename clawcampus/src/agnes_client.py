"""
Agnes-1.5-Pro client via ZenMux (OpenAI-compatible API).
Provides thin wrappers for heavy reasoning (Pro) and light chat (Lite).
"""
from __future__ import annotations

import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ZenMux endpoint — OpenAI-compatible
_client = OpenAI(
    base_url="https://zenmux.ai/api/v1",
    api_key=os.environ.get("AGNES_API_KEY", "sk-placeholder"),
)

MODEL_PRO = "agnes/agnes-1.5-pro"
MODEL_LITE = "agnes/agnes-1.5-lite"


def call_agnes_pro(messages: list[dict], temperature: float = 0.3) -> str:
    """Heavy reasoning: extraction, planning, summarization."""
    response = _client.chat.completions.create(
        model=MODEL_PRO,
        messages=messages,
        temperature=temperature,
    )
    return response.choices[0].message.content


def call_agnes_lite(messages: list[dict], temperature: float = 0.7) -> str:
    """Light follow-up chat to save tokens."""
    response = _client.chat.completions.create(
        model=MODEL_LITE,
        messages=messages,
        temperature=temperature,
    )
    return response.choices[0].message.content


def extract_json(text: str) -> list[dict] | dict | None:
    """Try to parse JSON from Agnes response, handling markdown fences."""
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON array or object in the text
        for start_char, end_char in [("[", "]"), ("{", "}")]:
            start = text.find(start_char)
            end = text.rfind(end_char)
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    continue
        return None


if __name__ == "__main__":
    # Quick smoke test
    print("Agnes client initialized.")
    print(f"  Pro model:  {MODEL_PRO}")
    print(f"  Lite model: {MODEL_LITE}")
    print(f"  Base URL:   {_client.base_url}")
    print(f"  API key:    {'set' if os.environ.get('AGNES_API_KEY') else 'placeholder'}")
