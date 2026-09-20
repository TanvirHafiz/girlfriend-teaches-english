"""Speech-to-text via faster-whisper, with a CUDA -> CPU fallback."""
import io
import logging

from faster_whisper import WhisperModel

logger = logging.getLogger("stt")

_model: WhisperModel | None = None


def get_model() -> WhisperModel:
    global _model
    if _model is not None:
        return _model
    try:
        _model = WhisperModel("large-v3", device="cuda", compute_type="float16")
        logger.info("faster-whisper loaded on CUDA (large-v3, float16)")
    except Exception as exc:  # noqa: BLE001
        logger.warning("CUDA whisper load failed (%s), falling back to CPU int8 small", exc)
        _model = WhisperModel("small", device="cpu", compute_type="int8")
    return _model


def transcribe(audio_bytes: bytes) -> tuple[str, str]:
    """Transcribe an audio blob (webm/opus, wav, etc). Returns (text, detected_language).

    Returns ("", "") for a clip with no detectable speech instead of raising: faster-whisper's
    language-id step throws `max() arg is an empty sequence` when its internal VAD trims a short
    or near-silent clip down to nothing.

    vad_filter is intentionally off: the browser client already runs its own voice-activity
    detection to decide when to start/stop recording, so every clip that reaches here is already
    what the client judged to be real speech. Layering Whisper's own (differently-calibrated,
    stricter) VAD on top of that was trimming genuine short utterances down to nothing.
    """
    model = get_model()
    buf = io.BytesIO(audio_bytes)
    try:
        segments, info = model.transcribe(
            buf,
            language="en",
            vad_filter=False,
            beam_size=5,
            condition_on_previous_text=False,
        )
        text = "".join(seg.text for seg in segments).strip()
        return text, info.language
    except ValueError as exc:
        if "max()" not in str(exc):
            raise
        logger.info("No speech detected in clip (%s)", exc)
        return "", ""
