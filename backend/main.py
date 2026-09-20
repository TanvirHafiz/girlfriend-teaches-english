import asyncio
import json
import logging
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.types import Scope

import llm
import stt
import tts
import vocab_bank
import vocab_notes
from personality import (
    PRACTICE_MODES,
    Profile,
    build_system_prompt,
    list_profiles,
    load_profile,
    save_profile,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

class NoCacheStaticFiles(StaticFiles):
    """This app's HTML/CSS/JS change constantly during development; browsers happily cache
    them across restarts and serve stale versions with no visible error, which is exactly
    what silently broke the vocab-panel styling. Force revalidation on every load."""

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        return response


app = FastAPI()
app.mount("/static", NoCacheStaticFiles(directory=FRONTEND_DIR), name="static")

MAX_HISTORY_MESSAGES = 20

# Kokoro-82M American English voices, best-graded first (per hexgrad/Kokoro-82M/VOICES.md).
CURATED_VOICES = [
    "af_heart",   # A / A - top-graded female voice
    "af_bella",   # A- / A-
    "af_nicole",  # B- / B-
    "af_sarah",   # B / C+
    "am_michael", # B / C+
    "am_fenrir",  # B / C+
    "am_puck",    # B / C+
]


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/voices")
async def get_voices():
    return CURATED_VOICES


@app.get("/api/practice-modes")
async def get_practice_modes():
    return PRACTICE_MODES


@app.get("/api/ollama/models")
async def get_ollama_models():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("http://localhost:11434/api/tags")
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"Could not reach Ollama at localhost:11434: {exc}"
        ) from exc
    return [m["name"] for m in resp.json().get("models", [])]


@app.get("/api/profiles")
async def get_profiles():
    return list_profiles()


@app.get("/api/profile/{profile_id}")
async def get_profile(profile_id: str):
    return load_profile(profile_id)


@app.post("/api/profile")
async def post_profile(profile: Profile):
    save_profile(profile)
    return {"ok": True}


class Session:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.history: list[dict] = []
        self.cancel_event = asyncio.Event()
        self.gen_task: asyncio.Task | None = None
        self.profile: Profile = load_profile()
        self.target_words: list[dict] = []


async def cancel_current_generation(session: Session):
    session.cancel_event.set()
    task = session.gen_task
    if task and not task.done():
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


async def send_vocab_update(session: Session, user_text: str, assistant_text: str):
    """Best-effort background pass: figure out which target words got used this turn and
    surface any other word the teacher explained, with a Bangla gloss. Fired without being
    awaited so it never delays the spoken reply or turn_end."""
    try:
        target_words = [w["word"] for w in session.target_words]
        prompt = vocab_notes.build_extraction_prompt(target_words, user_text, assistant_text)
        raw = await llm.complete(
            session.profile.ollama_model, vocab_notes.EXTRACTION_SYSTEM_PROMPT, prompt
        )
        result = vocab_notes.parse_extraction(raw)
        if result["used_target_words"] or result["difficult_words"]:
            await session.ws.send_json({"type": "vocab_update", **result})
    except Exception:  # noqa: BLE001
        logger.exception("vocab extraction failed")


async def handle_utterance(session: Session, audio_bytes: bytes):
    ws = session.ws
    try:
        text, _lang = await asyncio.to_thread(stt.transcribe, audio_bytes)
    except Exception as exc:  # noqa: BLE001
        logger.exception("STT failed")
        await ws.send_json({"type": "error", "message": f"STT failed: {exc}"})
        await ws.send_json({"type": "turn_end"})
        return

    text = text.strip()
    if not text:
        await ws.send_json({"type": "turn_end"})
        return

    await ws.send_json({"type": "transcript", "text": text})
    session.history.append({"role": "user", "content": text})

    profile = session.profile
    system_prompt = build_system_prompt(profile, session.target_words)
    assistant_parts: list[str] = []

    try:
        async for sentence in llm.stream_reply_sentences(
            profile.ollama_model, system_prompt, session.history, session.cancel_event
        ):
            if session.cancel_event.is_set():
                break
            spoken = tts.clean_for_speech(sentence)
            if not spoken:
                continue
            assistant_parts.append(spoken)
            try:
                audio = await asyncio.to_thread(tts.synthesize, spoken, profile.voice)
            except Exception as exc:  # noqa: BLE001
                logger.exception("TTS failed")
                await ws.send_json({"type": "error", "message": f"TTS failed: {exc}"})
                continue
            if session.cancel_event.is_set():
                break
            await ws.send_json({"type": "assistant_sentence", "text": spoken})
            await ws.send_bytes(audio)
    except asyncio.CancelledError:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM failed")
        await ws.send_json({"type": "error", "message": f"Could not reach Ollama: {exc}"})
    finally:
        if assistant_parts:
            assistant_text = " ".join(assistant_parts)
            session.history.append({"role": "assistant", "content": assistant_text})
        if len(session.history) > MAX_HISTORY_MESSAGES:
            session.history = session.history[-MAX_HISTORY_MESSAGES:]
        if not session.cancel_event.is_set():
            await ws.send_json({"type": "turn_end"})
            if assistant_parts:
                asyncio.create_task(send_vocab_update(session, text, assistant_text))


@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    await websocket.accept()
    session = Session(websocket)
    await websocket.send_json({"type": "ready"})

    try:
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                break

            text_data = msg.get("text")
            bytes_data = msg.get("bytes")

            if text_data is not None:
                data = json.loads(text_data)
                mtype = data.get("type")
                if mtype == "set_profile":
                    session.profile = load_profile(data.get("profile_id", "default"))
                    session.target_words = vocab_bank.pick_target_words(
                        session.profile.proficiency_level, session.profile.practice_mode
                    )
                    await websocket.send_json(
                        {"type": "lesson_words", "words": session.target_words}
                    )
                elif mtype == "barge_in":
                    await cancel_current_generation(session)
            elif bytes_data is not None:
                await cancel_current_generation(session)
                session.cancel_event = asyncio.Event()
                session.gen_task = asyncio.create_task(handle_utterance(session, bytes_data))
    except WebSocketDisconnect:
        pass
    finally:
        if session.gen_task and not session.gen_task.done():
            session.gen_task.cancel()
