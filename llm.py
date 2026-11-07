"""The AI's one job: read a supplier invoice photo into structured data.

It reports the header it sees (supplier, invoice number, date, printed total) and, for each
printed line, the matching ingredient, pack size + unit and price per pack, listing any field
it could not read clearly. It never calculates: code checks totals, duplicates and costs.
Code (engine.py) decides whether a line is verified or needs the owner's review.

Demo invoices never reach this module: engine.py matches their hash and uses
demo-data/invoices_extracted_fallback.json. Readings of new uploads are cached on disk
(llm_cache.json) by content hash, so the same file is never paid for twice.
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


def _client():
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=CONFIG.openrouter_api_key or "",  # empty key -> auth error -> handled below
        timeout=60,
        max_retries=1,
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
