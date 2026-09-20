# English Practice Partner — realtime voice ESL tutor

A local, almost-real-time voice conversation partner for practicing spoken English: you talk, she
listens (speech-to-text), thinks (a local Ollama model acting as an experienced ESL conversation
teacher), and talks back (text-to-speech), streamed sentence-by-sentence so she starts replying
before the whole answer is even generated. She keeps a real conversation going, gently corrects
grammar/word-choice mistakes by rephrasing them back correctly, and occasionally explains or
spells out new vocabulary.

- STT: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (local, GPU-accelerated, `large-v3`)
- LLM: [Ollama](https://ollama.com) running locally, any chat model
- TTS: [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) — small, Apache-2.0 licensed, local,
  fast enough to run on CPU alone (leaves the GPU free for the LLM and STT)
- Frontend: plain HTML/JS, browser mic capture with voice-activity detection (auto turn-taking, no
  push-to-talk) and barge-in (interrupt her by just talking)

## 1. Prerequisites

- Python 3.10 (a CUDA-capable NVIDIA GPU is used automatically for STT if present, else it falls
  back to CPU)
- [Ollama](https://ollama.com) installed, with a model pulled, e.g.:

```bash
ollama pull qwen2.5:3b-instruct
```

(Any chat-capable model works — just pick it in the setup screen's "Ollama model" dropdown. Smaller
models respond faster; Qwen models tend to have better multilingual/vocabulary breadth for their size.)

Then make sure the Ollama server is running (it usually runs in the background after install; if not):

```bash
ollama serve
```

## 2. Install backend dependencies

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

> Note: first run downloads model weights automatically — faster-whisper's `large-v3` (~3GB) and
> Kokoro's voice weights (~300MB), both cached locally afterward.

## 3. Run

```bash
cd backend
.venv\Scripts\activate
uvicorn main:app --port 8000
```

Open **http://localhost:8000** in Chrome or Edge (needed for mic support), allow microphone access,
set your English level and what you want to practice, and hit "Save & start call".

## How it works

1. Your mic audio is analyzed client-side (RMS-based voice activity detection, calibrated to your
   room's noise floor on call start) to detect when you start/stop talking — no button pressing needed.
2. Your utterance is sent to the backend over a WebSocket, transcribed with faster-whisper.
3. The transcript + conversation history + the ESL-teacher system prompt (calibrated to your chosen
   proficiency level) go to Ollama with streaming enabled.
4. As Ollama streams tokens, they're grouped into sentences; each finished sentence is immediately
   synthesized with Kokoro and streamed back to the browser as audio, so playback starts well before
   her full reply is done generating.
5. If you start talking while she's still speaking, the client detects it, tells the server to cancel
   the in-flight generation/TTS, and stops playback immediately — like a natural phone call interruption.

## Customizing

- Profiles are stored as JSON in `backend/profiles/`. The setup screen currently manages a single
  `default` profile, but `personality.py` supports multiple named profiles if you want to extend the
  UI to switch between them.
- Voice choices come from `CURATED_VOICES` in `backend/main.py`, picked from Kokoro's best-graded
  American English voices (see [VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md)
  for the full catalog across other languages/accents).
- Tune `SILENCE_TO_STOP_MS`, `CONTINUE_THRESHOLD_RATIO`, and `BARGE_IN_SUSTAIN_MS` at the top of
  `frontend/app.js` if turn-taking feels too eager, too sluggish, or clips off your last word.
- Teaching behavior (how often to correct, when to spell words out, vocabulary calibration per level)
  lives in `LEVEL_INSTRUCTIONS` and `build_system_prompt` in `backend/personality.py`.

## Next steps / ideas

- A lightweight "corrections" panel showing what was fixed each turn, separate from the spoken reply.
- Topic/scenario prompts (ordering food, a job interview, small talk) to target specific practice needs.
- True streaming STT (partial transcripts while you're still talking) for even lower latency and
  mid-sentence interruption handling.
