# Night Shift 🌙

Overnight AI back-office agent for small restaurants (DoorDash "Back House" track).
Reads a supplier invoice, updates ingredient costs, finds dishes that lose money on
DoorDash, and has AI-drafted, code-priced fixes waiting in a 7 AM Brief.

## Run

```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY=sk-or-...   # optional: falls back to cached data without it
streamlit run app.py
```

Optional: `NIGHT_SHIFT_MODEL` (default `anthropic/claude-sonnet-5.5`).

## How it works

| File | Job |
|---|---|
| `data.py` | Seed menu, recipes, ingredient prices for "Pho Real". Brisket +12% is the planted problem. |
| `margins.py` | All math, no AI. DoorDash margin = price − 25% − $0.50 packaging − food cost. |
| `llm.py` | AI reads the invoice and *proposes* fixes. It never computes margins. Hardcoded fallbacks if the API fails. |
| `app.py` | Streamlit UI: Night Shift run → Margins → 7 AM Brief (approve/reject + trust ladder). |
| `make_invoice.py` | Draws `sample_invoice.png`. |
