"""Streaming chat against a local Ollama server, with sentence-level chunking
so downstream TTS can start speaking before the full reply is generated."""
import asyncio
import json
import re
from typing import AsyncIterator

import httpx

OLLAMA_URL = "http://localhost:11434/api/chat"

# Sentence terminators, including Bangla's danda (।).
_SENTENCE_END_RE = re.compile(r"([.!?।]+)\s*")


async def stream_reply_tokens(
    model: str,
    system_prompt: str,
    history: list[dict],
    cancel_event: asyncio.Event,
) -> AsyncIterator[str]:
    """Yield raw text tokens from Ollama as they arrive. Stops early if cancel_event is set."""
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}, *history],
        "stream": True,
        "options": {"temperature": 0.9},
        # Keep the model resident in VRAM well past a normal conversational pause. Reloading a
        # 24B model from disk after Ollama's default 5-minute idle unload costs well over a
        # minute before the first token, which feels like the app hanging.
        "keep_alive": "30m",
    }
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", OLLAMA_URL, json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if cancel_event.is_set():
                    return
                if not line.strip():
                    continue
                chunk = json.loads(line)
                if chunk.get("done"):
                    return
                token = chunk.get("message", {}).get("content", "")
                if token:
                    yield token


async def complete(model: str, system_prompt: str, user_prompt: str) -> str:
    """Single non-streaming completion for small background/structured tasks (not real-time
    voice), e.g. vocabulary extraction after a turn. Reuses the same model already loaded for
    conversation, since calling a different model would force Ollama to swap it out of VRAM."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.2},
        "keep_alive": "30m",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(OLLAMA_URL, json=payload)
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")


async def stream_reply_sentences(
    model: str,
    system_prompt: str,
    history: list[dict],
    cancel_event: asyncio.Event,
) -> AsyncIterator[str]:
    """Buffer tokens into complete sentences and yield each as soon as it's ready."""
    buffer = ""
    async for token in stream_reply_tokens(model, system_prompt, history, cancel_event):
        buffer += token
        while True:
            match = _SENTENCE_END_RE.search(buffer)
            if not match:
                break
            end = match.end()
            sentence = buffer[:end].strip()
            buffer = buffer[end:]
            if sentence:
                yield sentence
            if cancel_event.is_set():
                return
    remainder = buffer.strip()
    if remainder and not cancel_event.is_set():
        yield remainder
