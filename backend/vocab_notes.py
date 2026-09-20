"""Background, non-blocking extraction of vocabulary teaching notes from a finished turn:
which target lesson words got used, plus any other word the teacher explained that's worth
surfacing with a Bangla gloss. Runs after the spoken reply, never delays it."""
import json
import re

EXTRACTION_SYSTEM_PROMPT = """You analyze one turn of an ESL (English as a Second Language) \
lesson conversation and output STRICT JSON only — no markdown, no explanation, nothing \
before or after the JSON object.

Output exactly this shape:
{"used_target_words": ["word1"], "difficult_words": [{"word": "example", "bangla": "..."}]}

Rules:
- "used_target_words": from the TARGET WORD LIST given, list only the ones the teacher actually \
used or explained in her reply this turn. Empty list if none.
- "difficult_words": any OTHER vocabulary word or short phrase (not already in the target list) \
that the teacher explicitly explained, defined, or corrected in her reply this turn, because \
it's likely new or difficult for the student. Give each an accurate Bangla translation. Do not \
include simple everyday words the student clearly already knows. Empty list if none.
- Output ONLY the JSON object.
"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def build_extraction_prompt(target_words: list[str], user_text: str, assistant_text: str) -> str:
    words_line = ", ".join(target_words) if target_words else "(none)"
    return (
        f"TARGET WORD LIST: {words_line}\n\n"
        f"Student said: {user_text}\n"
        f"Teacher replied: {assistant_text}\n\n"
        "Output the JSON now."
    )


def parse_extraction(raw: str) -> dict:
    """Defensively parse the model's JSON. Returns empty lists on any malformed output instead
    of raising, since this is a best-effort supplementary feature."""
    empty = {"used_target_words": [], "difficult_words": []}
    match = _JSON_RE.search(raw)
    if not match:
        return empty
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return empty
    if not isinstance(data, dict):
        return empty

    used = data.get("used_target_words", [])
    used = [str(w).strip() for w in used if isinstance(w, str) and w.strip()] if isinstance(used, list) else []

    difficult = data.get("difficult_words", [])
    difficult = (
        [
            {"word": str(d.get("word", "")).strip(), "bangla": str(d.get("bangla", "")).strip()}
            for d in difficult
            if isinstance(d, dict) and d.get("word") and d.get("bangla")
        ]
        if isinstance(difficult, list)
        else []
    )

    return {"used_target_words": used, "difficult_words": difficult}
