"""Night Shift: an overnight AI back-office agent for small restaurants.

Flow:  invoice photo -> AI extracts prices -> code recomputes margins
       -> AI drafts fixes for money-losing DoorDash dishes -> code prices each fix
       -> owner approves/rejects in the 7 AM Brief (and builds trust over time).

Run:   streamlit run app.py
"""

import copy
from pathlib import Path

import pandas as pd
import streamlit as st

import llm
from data import INGREDIENTS, MENU, RESTAURANT_NAME, baseline_prices
from make_invoice import make_invoice
from margins import compute_margins, evaluate_fix, price_change

SAMPLE_INVOICE_PATH = Path(__file__).parent / "sample_invoice.png"
AUTO_APPROVE_LIMIT = 2.00   # trust ladder: auto-approve price fixes under $2
TRUST_THRESHOLD = 3         # ask about auto-approve after this many approvals

st.set_page_config(page_title="Night Shift", page_icon="🌙", layout="wide")

# ------------------------------------------------------------------ styling

st.markdown("""
<style>
  .ns-header {background: linear-gradient(135deg, #0B1F3A 0%, #13305A 100%);
              padding: 22px 28px; border-radius: 14px; margin-bottom: 18px;
              border-bottom: 4px solid #F2A541;}
  .ns-header h1 {color: #fff !important; margin: 0; font-size: 2.1rem; letter-spacing: .5px;}
  .ns-header h1 span {color: #F2A541 !important;}
  .ns-header p {color: #C9D3E3; margin: 4px 0 0 0;}
  .ns-banner {background: #FFF6E8; border-left: 6px solid #F2A541; color: #0B1F3A;
              padding: 16px 20px; border-radius: 10px; font-size: 1.05rem; margin: 8px 0;}
  .ns-loss {color: #C62828; font-weight: 700;}
  .ns-gain {color: #2E7D32; font-weight: 700;}
  .stButton button[kind="primary"] {color: #0B1F3A; font-weight: 600;}
</style>
<div class="ns-header">
  <h1>🌙 Night <span>Shift</span></h1>
  <p>Overnight back-office agent for <b>RESTAURANT</b>. Reads invoices, watches DoorDash margins,
     and has a brief ready by 7 AM.</p>
</div>
""".replace("RESTAURANT", RESTAURANT_NAME), unsafe_allow_html=True)

# ------------------------------------------------------------------ state

def init_state():
    defaults = {
        "prices": baseline_prices(),   # current ingredient cost per unit
        "price_changes": {},           # key -> (old, new) from the last run
        "extracted": None,             # what the AI read off the invoice
        "used_fallback": False,
        "brief": [],                   # flagged dishes + priced fixes
        "decisions": {},               # fix id -> "approved" / "rejected"
        "doordash_overrides": {},      # dish -> approved new DoorDash price
        "auto_approve": None,          # trust ladder answer: True / False / None
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def current_menu():
    """The menu with any approved DoorDash price changes applied."""
    menu = copy.deepcopy(MENU)
    for dish, price in st.session_state.doordash_overrides.items():
        menu[dish]["doordash_price"] = price
    return menu


init_state()
if not SAMPLE_INVOICE_PATH.exists():
    make_invoice(str(SAMPLE_INVOICE_PATH))

with st.sidebar:
    st.markdown("### Demo controls")
    if st.button("Reset to yesterday's prices", width="stretch"):
        st.session_state.clear()
        st.rerun()
    st.caption(f"Model: `{llm.MODEL}` via OpenRouter")


# ------------------------------------------------------------------ the overnight job

def run_night_shift(image_bytes, mime_type):
    """The whole overnight pipeline. AI reads and suggests; code does the math."""
    with st.status("Night Shift is working...", expanded=True) as status:
        st.write("📄 Reading supplier invoice...")
        extracted, used_fallback = llm.extract_invoice(image_bytes, mime_type)

        st.write("🧮 Updating ingredient costs...")
        prices = dict(st.session_state.prices)
        changes = {}
        for item in extracted:
            old, new = prices[item["ingredient"]], item["unit_price"]
            if abs(new - old) > 0.001:
                changes[item["ingredient"]] = (old, new)
            prices[item["ingredient"]] = new

        st.write("📊 Recomputing margins for every dish...")
        _, flagged = compute_margins(prices, current_menu())

        brief = []
        for item in flagged:
            st.write(f"💡 Drafting fixes for **{item['dish']}**...")
            fixes, fixes_fallback = llm.suggest_fixes(item)
            priced = []
            for i, fix in enumerate(fixes):
                new_margin = evaluate_fix(fix, item["dish"], prices, current_menu())
                if new_margin is None:   # model proposed something we can't price
                    continue
                priced.append({**fix, "id": f"{item['dish']}::{i}",
                               "new_margin": round(new_margin, 2),
                               "price_change": round(price_change(fix, item["dish"], current_menu()), 2)})
            causes = {k: v for k, v in changes.items() if k in item["recipe"]}
            brief.append({**item, "fixes": priced, "causes": causes,
                          "used_fallback": fixes_fallback})

        st.session_state.update(prices=prices, price_changes=changes, extracted=extracted,
                                used_fallback=used_fallback, brief=brief, decisions={})
        status.update(label=f"Done. Found {len(brief)} issue(s). Your 7 AM Brief is ready.",
                      state="complete", expanded=False)


def decide(fix, dish, decision):
    st.session_state.decisions[fix["id"]] = decision
    if decision == "approved" and fix["type"] == "raise_price":
        st.session_state.doordash_overrides[dish] = float(fix["new_doordash_price"])


def money(value, signed=False):
    sign = "-" if value < 0 else ("+" if signed else "")
    return f"{sign}${abs(value):,.2f}"


def md(text):
    """Escape $ so Streamlit markdown doesn't render '$11.50 ... $12.88' as LaTeX math."""
    return text.replace("$", r"\$")


# ------------------------------------------------------------------ tabs

tab_run, tab_margins, tab_brief = st.tabs(["🌙 Night Shift run", "📊 Margins", "☀️ 7 AM Brief"])

with tab_run:
    left, right = st.columns([1, 1], gap="large")
    with left:
        st.subheader("1. Drop in tonight's invoice")
        uploaded = st.file_uploader("Supplier invoice photo", type=["png", "jpg", "jpeg", "webp"])
        if uploaded:
            image_bytes, mime_type = uploaded.getvalue(), uploaded.type
        else:
            st.caption("No upload? Night Shift will use the sample invoice from Saigon Wholesale.")
            image_bytes, mime_type = SAMPLE_INVOICE_PATH.read_bytes(), "image/png"
        if st.button("▶ Run Night Shift", type="primary", width="stretch"):
            run_night_shift(image_bytes, mime_type)
    with right:
        st.image(image_bytes, caption="Invoice being processed", width="stretch")

    if st.session_state.extracted:
        st.subheader("2. What Night Shift read")
        if st.session_state.used_fallback:
            st.warning("AI extraction unavailable, so Night Shift used cached invoice prices.")
        rows = []
        for item in st.session_state.extracted:
            key = item["ingredient"]
            old, new = st.session_state.price_changes.get(key, (item["unit_price"],) * 2)
            rows.append({"Ingredient": INGREDIENTS[key]["name"],
                         "Unit": INGREDIENTS[key]["unit"],
                         "Old price": old, "New price": new,
                         "Change": (new - old) / old})
        st.dataframe(
            pd.DataFrame(rows).style
            .format({"Old price": "${:.2f}", "New price": "${:.2f}", "Change": "{:+.0%}"})
            .apply(lambda r: ["background-color: #FFF6E8; font-weight: 600"] * len(r)
                   if abs(r["Change"]) > 0.001 else [""] * len(r), axis=1),
            hide_index=True, width="stretch")
        c1, c2, c3 = st.columns(3)
        c1.metric("Prices read", len(st.session_state.extracted))
        c2.metric("Prices changed", len(st.session_state.price_changes))
        c3.metric("Dishes losing money on DoorDash", len(st.session_state.brief))

with tab_margins:
    df, flagged_now = compute_margins(st.session_state.prices, current_menu())
    st.subheader("Every dish, in-store vs DoorDash")
    st.caption("DoorDash margin = price − 25% commission − $0.50 packaging − food cost. "
               "Computed in plain Python; no AI involved.")
    st.dataframe(
        df.style
        .format({col: "${:.2f}" for col in df.columns if col != "Dish"})
        .apply(lambda r: ["background-color: #FDE2E1; color: #9B1C1C; font-weight: 600"] * len(r)
               if r["DoorDash margin"] < 0 else [""] * len(r), axis=1),
        hide_index=True, width="stretch")
    if flagged_now:
        st.error(f"{len(flagged_now)} dish(es) lose money on every DoorDash order.")
    else:
        st.success("Every dish makes money on DoorDash.")

with tab_brief:
    brief = st.session_state.brief
    st.header(f"Good morning. Night Shift found {len(brief)} issue{'s' if len(brief) != 1 else ''}.")
    if st.session_state.extracted is None:
        st.info("Night Shift hasn't run yet. Start a run in the first tab.")

    approved = sum(1 for d in st.session_state.decisions.values() if d == "approved")

    # Trust ladder: after enough approvals, offer to let Night Shift act alone on small fixes.
    if approved >= TRUST_THRESHOLD and st.session_state.auto_approve is None:
        st.markdown(f'<div class="ns-banner">🤝 <b>You\'ve approved {approved} price fixes.</b> '
                    f'Auto-approve fixes under ${AUTO_APPROVE_LIMIT:.0f} in future?</div>',
                    unsafe_allow_html=True)
        yes, no, _ = st.columns([1, 1, 4])
        if yes.button("Yes, auto-approve", type="primary"):
            st.session_state.auto_approve = True
            st.rerun()
        if no.button("Not yet"):
            st.session_state.auto_approve = False
            st.rerun()
    elif st.session_state.auto_approve:
        st.success(f"Auto-approve is on: fixes that raise a price by less than "
                   f"${AUTO_APPROVE_LIMIT:.2f} will be applied overnight and listed here.")

    for item in brief:
        with st.container(border=True):
            st.subheader(item["dish"])
            for key, (old, new) in item["causes"].items():
                st.markdown(md(f"**Why:** {INGREDIENTS[key]['name']} went from ${old:.2f} → "
                               f"${new:.2f}/{INGREDIENTS[key]['unit']} ({(new - old) / old:+.0%})."))
            m1, m2, m3 = st.columns(3)
            m1.metric("Loss per DoorDash order", money(-item["loss_per_order"]))
            m2.metric("In-store margin (still fine)", money(item["in_store_margin"]))
            m3.metric("DoorDash break-even price", money(item["break_even_doordash_price"]))

            st.markdown("**Suggested fixes** (AI proposed · margins computed by code)")
            if item["used_fallback"]:
                st.caption("AI unavailable, so these are rule-based backup suggestions.")
            for fix in item["fixes"]:
                status = st.session_state.decisions.get(fix["id"])
                text, buttons = st.columns([4, 1.4])
                with text:
                    gain = fix["new_margin"] - item["doordash_margin"]
                    css = "ns-gain" if fix["new_margin"] >= 0 else "ns-loss"
                    st.markdown(md(
                        f"**{fix['title']}**  \n{fix['rationale']}  \n"
                        f"New DoorDash margin: <span class='{css}'>{money(fix['new_margin'])}</span> "
                        f"per order ({money(gain, signed=True)} vs today)"), unsafe_allow_html=True)
                with buttons:
                    if status == "approved":
                        st.markdown(":green[**✓ Approved**]")
                    elif status == "rejected":
                        st.markdown(":gray[✗ Rejected]")
                    else:
                        a, r = st.columns(2)
                        a.button("Approve", key=f"a-{fix['id']}", type="primary",
                                 on_click=decide, args=(fix, item["dish"], "approved"))
                        r.button("Reject", key=f"r-{fix['id']}",
                                 on_click=decide, args=(fix, item["dish"], "rejected"))

    if brief:
        st.caption(f"{approved} fix(es) approved so far. Approved DoorDash price changes "
                   "show up in the Margins tab.")
