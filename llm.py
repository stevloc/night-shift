"""The two AI calls in Night Shift. Both go through OpenRouter with the same key and model.

1. extract_invoice(): read a supplier invoice photo/PDF into structured data.
   It reports the header it sees (supplier, invoice number, date, printed total) and, for each
   printed line, the matching ingredient, pack size + unit and price per pack, listing any field
   it could not read clearly. It never calculates: code checks totals, duplicates and costs.
   Code (engine.py) decides whether a line is verified or needs the owner's review.
   Demo invoices never reach this function: engine.py matches their hash and uses
   demo-data/invoices_extracted_fallback.json. Readings of new uploads are cached on disk
   (llm_cache.json) by content hash, so the same file is never paid for twice.

2. review_decision(): one owner-triggered "Review my options" call (review.py builds the prompt from
   the code-computed snapshot and validates the answer). Bounded timeout and output, no retries.

3. chat_turn(): one turn of the "Investigate this alert" tool loop (investigate.py runs the loop, the
   allowlisted tools and every limit). Same key and model; no retries.

The API key is read from the environment only (OPENROUTER_API_KEY).
"""

import base64
import hashlib
import json
import re
import threading
from pathlib import Path

from openai import OpenAI

from config import CONFIG
from data import INGREDIENTS, UNITS

MODEL = CONFIG.openrouter_model
CACHE_PATH = Path(__file__).parent / "llm_cache.json"

_lock = threading.Lock()
try:
    _cache = json.loads(CACHE_PATH.read_text())
except (OSError, ValueError):
    _cache = {}


def is_cached(file_bytes):
    return _cache_key(hashlib.sha256(file_bytes).hexdigest()) in _cache


def _cache_key(image_hash):
    return f"invoice-v4:{MODEL}:{image_hash}"


def _client(timeout=60, max_retries=1):
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=CONFIG.openrouter_api_key or "",  # empty key -> auth error -> handled below
        timeout=timeout,
        max_retries=max_retries,
    )


def _parse_json(text):
    """Models sometimes wrap JSON in ```fences``` or prose; grab the JSON object."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(match.group(0) if match else text)


def _clean_line(raw):
    """Keep only well-formed values; anything doubtful becomes None and is marked unclear."""
    unclear = set(raw.get("unclear") or [])

    def number(name):
        try:
            value = float(raw.get(name))
            return value if value > 0 else None
        except (TypeError, ValueError):
            return None

    line = {
        "original": str(raw.get("original") or "").strip(),
        "quantity": number("quantity"),
        "ingredient": raw.get("ingredient") if raw.get("ingredient") in INGREDIENTS else None,
        "pack_size": number("pack_size"),
        "pack_unit": raw.get("pack_unit") if raw.get("pack_unit") in UNITS else None,
        "pack_price": number("pack_price"),
    }
    for field in ("ingredient", "pack_size", "pack_unit", "pack_price"):
        if line[field] is None:
            unclear.add(field)
    line["unclear"] = sorted(unclear)
    return line


def _clean_header(raw):
    def text(name):
        value = raw.get(name)
        return str(value).strip() if value not in (None, "") else ""
    try:
        total = round(float(raw.get("total")), 2)
    except (TypeError, ValueError):
        total = None
    return {"supplier": text("supplier"), "invoice_no": text("invoice_no"), "date": text("date"), "total": total}


def extract_invoice(image_bytes, mime_type="image/png", fallback=None):
    """Returns (invoice, used_fallback): {supplier, invoice_no, date, total, lines: [...]}.

    `fallback` (a seeded reading) is used only if the AI can't be reached.
    """
    image_hash = hashlib.sha256(image_bytes).hexdigest()
    cached = _cache.get(_cache_key(image_hash))
    if cached is not None:
        return cached, False

    known = "\n".join(f"- {key}: {info['name']['en']}" for key, info in INGREDIENTS.items())
    prompt = (
        "You are reading a restaurant supplier invoice. Report the header exactly as printed: "
        "supplier (company name), invoice_no, date, and total (the 'Total due' amount). "
        "Then, for EACH printed line item, report:\n"
        "- original: the line description exactly as printed\n"
        "- quantity: how many packs were ordered\n"
        "- ingredient: the matching key from the list below, or null if none fits\n"
        "- pack_size and pack_unit: the size of ONE pack as printed (unit one of: lb, kg, oz, g, each, sheet). "
        "'50 ct' means 50 each. If the pack size is not printed (e.g. just '1 cs'), use null.\n"
        "- pack_price: the price for ONE pack (the unit price column)\n"
        "- unclear: list the field names you could not read with confidence\n"
        "Do not guess and do not calculate anything.\n\n"
        f"Known ingredients:\n{known}\n\n"
        'Reply with JSON only: {"supplier": "", "invoice_no": "", "date": "", "total": 0, '
        '"lines": [{"original": "", "quantity": 0, "ingredient": "", '
        '"pack_size": 0, "pack_unit": "", "pack_price": 0, "unclear": []}]}'
    )
    data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"
    attachment = ({"type": "file", "file": {"filename": "invoice.pdf", "file_data": data_url}}
                  if mime_type == "application/pdf" else {"type": "image_url", "image_url": {"url": data_url}})
    try:
        response = _client().chat.completions.create(
            model=MODEL, temperature=0,
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, attachment]}],
        )
        raw = _parse_json(response.choices[0].message.content)
        lines = [line for line in (_clean_line(r) for r in raw.get("lines", [])) if line["original"]]
        if not lines:
            raise ValueError("no line items found")
        invoice = {**_clean_header(raw), "lines": lines}
        with _lock:
            _cache[_cache_key(image_hash)] = invoice
            CACHE_PATH.write_text(json.dumps(_cache, indent=1, ensure_ascii=False))
        return invoice, False
    except Exception as error:  # network, auth, bad JSON... never break the demo
        print(f"[night-shift] invoice reading failed: {error}")
        if not fallback:
            return None, True
        return {**fallback, "lines": [dict(line) for line in fallback["lines"]]}, True


REVIEW_TIMEOUT_SECONDS = 25
REVIEW_MAX_TOKENS = 900


def review_decision(system, user):
    """One decision-review call. Returns the parsed JSON object; raises on any failure (the caller
    shows an honest "unavailable" state). No retries, bounded time and output, temperature 0."""
    response = _client(timeout=REVIEW_TIMEOUT_SECONDS, max_retries=0).chat.completions.create(
        model=MODEL, temperature=0, max_tokens=REVIEW_MAX_TOKENS,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return _parse_json(response.choices[0].message.content or "")


# ------------------------------------------------------------------ investigator (tool calling)

_TOOL_SUPPORT = {}   # model -> True / False, from OpenRouter's model list (checked once per process)


def supports_tools(timeout=5):
    """True / False if OpenRouter lists whether the configured model accepts `tools`; None if unknown."""
    if MODEL in _TOOL_SUPPORT:
        return _TOOL_SUPPORT[MODEL]
    try:
        import httpx
        r = httpx.get("https://openrouter.ai/api/v1/models", timeout=timeout)
        r.raise_for_status()
        model = next((m for m in r.json().get("data", []) if m.get("id") == MODEL), None)
    except Exception as error:
        print(f"[night-shift] could not check tool support: {type(error).__name__}")
        return None   # unknown: try the call; a provider error is reported as unavailable
    _TOOL_SUPPORT[MODEL] = bool(model and "tools" in (model.get("supported_parameters") or []))
    return _TOOL_SUPPORT[MODEL]


def chat_turn(messages, tools, final, timeout, max_tokens=900):
    """One model turn. `final` keeps the tool list visible but forbids calling it (tool_choice="none").
    Returns the assistant message (content + tool_calls); raises on any failure."""
    response = _client(timeout=timeout, max_retries=0).chat.completions.create(
        model=MODEL, temperature=0, max_tokens=max_tokens, messages=messages,
        tools=tools, tool_choice="none" if final else "auto",
    )
    return response.choices[0].message
