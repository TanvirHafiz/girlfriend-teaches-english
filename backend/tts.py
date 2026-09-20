"""Text-to-speech via Kokoro-82M: small, local, Apache-2.0 licensed, fast enough on CPU
alone that it leaves the GPU free for the LLM and STT."""
import io
import re
import warnings

import numpy as np
import soundfile as sf

warnings.filterwarnings("ignore", category=FutureWarning)

# Emoji/pictographs, dingbats, variation selectors, ZWJ, skin-tone modifiers, regional
# indicators. TTS engines read these aloud by name ("grinning face") instead of skipping them.
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "\U0000FE0F"
    "\U0000200D"
    "\U000020E3"
    "]+",
    flags=re.UNICODE,
)
# Markdown emphasis/heading characters. Stripped as bare characters, never with their
# contents, since models routinely **bold** real words that must still be spoken.
_MARKDOWN_CHARS_RE = re.compile(r"[*_#`]")


def clean_for_speech(text: str) -> str:
    """Strip anything a TTS engine would mispronounce: emoji, markdown formatting chars."""
    text = _EMOJI_RE.sub("", text)
    text = _MARKDOWN_CHARS_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


_pipeline = None
SAMPLE_RATE = 24000


def get_pipeline():
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    from kokoro import KPipeline

    _pipeline = KPipeline(lang_code="a")  # American English
    return _pipeline


def synthesize(text: str, voice: str) -> bytes:
    """Synthesize text to WAV bytes using the given Kokoro voice. CPU-bound and
    synchronous — call via asyncio.to_thread from async code."""
    pipeline = get_pipeline()
    chunks = [result.audio.numpy() for result in pipeline(text, voice=voice)]
    audio = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
    buf = io.BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="WAV")
    return buf.getvalue()
