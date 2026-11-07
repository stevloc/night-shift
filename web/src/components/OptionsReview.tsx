// "Review my options": a compact panel in the dish's decision area.
//   1. Code compares the options (keep / suggested / your price / your limit) from the server snapshot.
//   2. Optionally, "Investigate this alert": one bounded AI investigation (Investigator.tsx).
// Every figure comes from the server (snapshot or calculator), never from the AI. Nothing here changes data:
// the owner still decides with Approve / Change price / Keep / Dismiss above.

import { useEffect, useId, useState } from "react";
import { api, type Dish, type Limits, type OptionId, type PriceOption, type Snapshot } from "../api";
import { useApp } from "../context";
import { dishName, errorText, fieldError, fieldErrors } from "../format";
import type { I18n, Key } from "../i18n";
import { Icon } from "./Icon";
import { Investigator } from "./Investigator";

export function OptionsReview({ dish }: { dish: Dish }) {
  const { view, i18n } = useApp();
  const { t } = i18n;
  const id = useId();
  const [open, setOpen] = useState(false);
  const [limits, setLimits] = useState<Limits>({ max_price: "", max_increase: "" });
  const [note, setNote] = useState("");
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [focus, setFocus] = useState<OptionId | null>(null);

  // Deterministic comparison: refetched when the limit changes and whenever the app's data changes.
  useEffect(() => {
    if (!open) return;
    const timer = window.setTimeout(async () => {
      try {
        setSnap((await api.options(dish.id, limits)).snapshot);
        setErrors({});
      } catch (e) {
        const f = fieldErrors(e);
        setErrors(Object.keys(f).length ? f : { form: errorText(e, i18n) });
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [open, dish.id, limits.max_price, limits.max_increase, view, i18n]);

  const priced = snap?.options.filter((o) => o.id !== "keep_current") ?? [];
  const shown = priced.find((o) => o.id === focus) ?? priced.find((o) => o.id === "custom")
    ?? priced.find((o) => o.id === "limit") ?? priced[0];

  return (
    <section className="options-review" aria-labelledby={`${id}-h`}>
      <button type="button" className="btn" aria-expanded={open} aria-controls={`${id}-panel`}
        onClick={() => setOpen(!open)}>
        <Icon name="eye" /><span id={`${id}-h`}>{t("rv_open")}</span>
      </button>
      <div id={`${id}-panel`} className="rec-block stack" hidden={!open}>
        <p className="hint">{t("rv_intro")}</p>
        <div className="field-row">
          <div className="field">
            <label htmlFor={`${id}-max`}>{t("rv_max_price")}</label>
            <input id={`${id}-max`} type="text" inputMode="decimal" autoComplete="off" value={limits.max_price}
              placeholder={i18n.money(dish.now.price + 1)}
              onChange={(e) => setLimits({ ...limits, max_price: e.target.value })}
              aria-invalid={!!errors.max_price} aria-describedby={errors.max_price ? `${id}-max-err` : undefined} />
            {errors.max_price && <p id={`${id}-max-err`} className="field-error"><Icon name="alert" size={18} />
              {errors.max_price === "below_current" ? t("rv_below_current", { price: i18n.money(dish.now.price) }) : fieldError(errors.max_price, i18n)}</p>}
          </div>
          <div className="field">
            <label htmlFor={`${id}-inc`}>{t("rv_max_increase")}</label>
            <input id={`${id}-inc`} type="text" inputMode="decimal" autoComplete="off" value={limits.max_increase}
              placeholder={i18n.money(0.5)}
              onChange={(e) => setLimits({ ...limits, max_increase: e.target.value })}
              aria-invalid={!!errors.max_increase} aria-describedby={errors.max_increase ? `${id}-inc-err` : undefined} />
            {errors.max_increase && <p id={`${id}-inc-err`} className="field-error"><Icon name="alert" size={18} />{fieldError(errors.max_increase, i18n)}</p>}
          </div>
        </div>
        <div className="field">
          <label htmlFor={`${id}-note`}>{t("rv_note")}</label>
          <textarea id={`${id}-note`} rows={2} maxLength={280} value={note} placeholder={t("rv_note_example")}
            onChange={(e) => setNote(e.target.value)} />
          <p className="hint">{t("rv_note_hint")}</p>
        </div>
        {errors.form && <p className="field-error"><Icon name="alert" size={18} />{errors.form}</p>}

        {snap && (
          <>
            <OptionCards snap={snap} />
            {snap.conflicts.map((c) => (
              <p key={c.kind} className="notice warn"><Icon name="alert" />
                {t(c.best_reaches_target ? "rv_conflict_ok" : "rv_conflict", {
                  limit: i18n.money(c.limit), target_price: i18n.money(c.target_price),
                  pct: i18n.pctPoints(c.best_margin), target: i18n.pctPoints(snap.settings.target_margin_pct) })}</p>
            ))}
            {shown && <SensitivityTable snap={snap} option={shown} options={priced} onPick={setFocus} />}
            <p className="hint row"><Icon name="info" size={16} />{t("excluded")}</p>

            <Investigator dish={dish} limits={limits} note={note} version={snap.version} />
          </>
        )}
      </div>
    </section>
  );
}

function optionName(id: OptionId, i18n: I18n) {
  return i18n.t(`opt_${id}` as Key);
}

/** One card per option: price, amount left, share of price, target and limit. Figures from the server. */
function OptionCards({ snap }: { snap: Snapshot }) {
  const { i18n } = useApp();
  const { t, money, pctPoints, approx } = i18n;
  return (
    <ul className="option-cards" aria-label={t("rv_options")}>
      {snap.options.map((o) => (
        <li key={o.id}>
          <p className="option-name">{optionName(o.id, i18n)}</p>
          <p className="option-price">{money(o.price)}</p>
          <p>{t("rv_left", { left: money(o.after.left), pct: pctPoints(o.after.margin_pct) })}</p>
          <p className={o.reaches_target ? "text-good" : "text-warn"}>
            <Icon name={o.reaches_target ? "checkCircle" : "alert"} size={16} />
            {t(o.reaches_target ? "rv_reaches" : "rv_below", { target: pctPoints(snap.settings.target_margin_pct) })}
          </p>
          {o.within_limit === false && <p className="text-warn"><Icon name="alert" size={16} />{t("rv_over_limit")}</p>}
          {o.id !== "keep_current" && (
            <p className="hint">{t("rv_change", { per: money(o.per_order_change, true) })}
              {o.monthly_change !== null && <> · {t("rv_monthly", { monthly: approx(o.monthly_change) })}</>}</p>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Hypothetical order-volume cases for one option, always vs. today's baseline. Not a forecast. */
function SensitivityTable({ snap, option, options, onPick }: {
  snap: Snapshot; option: PriceOption; options: PriceOption[]; onPick: (id: OptionId) => void;
}) {
  const { i18n } = useApp();
  const { t, money, num } = i18n;
  const id = useId();
  const s = option.sensitivity;
  return (
    <div className="stack sensitivity">
      <h5 id={`${id}-h`}>{t("rv_sens_title")}</h5>
      {options.length > 1 && (
        <div className="row" role="group" aria-labelledby={`${id}-h`}>
          {options.map((o) => (
            <button key={o.id} type="button" className="btn" aria-pressed={o.id === option.id} onClick={() => onPick(o.id)}>
              {optionName(o.id, i18n)} ({money(o.price)})
            </button>
          ))}
        </div>
      )}
      {!s || !s.available ? <p className="hint">{t("rv_sens_unavailable")}</p> : (
        <>
          <div className="table-wrap" role="region" aria-labelledby={`${id}-h`} tabIndex={0}>
            <table className="calc">
              <caption className="sr-only">{t("rv_sens_caption", { option: optionName(option.id, i18n) })}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("rv_case")}</th>
                  <th scope="col" className="num">{t("rv_orders")}</th>
                  <th scope="col" className="num">{t("rv_vs_today")}</th>
                </tr>
              </thead>
              <tbody>
                {s.cases!.map((c) => (
                  <tr key={c.decline}>
                    <th scope="row">{c.decline === 0 ? t("rv_case_same") : t("rv_case_fewer", { pct: i18n.pct(c.decline) })}</th>
                    <td className="num">{num(Math.round(c.orders))}</td>
                    <td className={`num ${c.change < -0.004 ? "text-bad" : ""}`}>{money(c.change, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>{thresholdText(s.threshold!, option, i18n)}</p>
          <p className="hint">{t("rv_sens_basis", { orders: num(snap.monthly_orders), now: money(snap.now.left), after: money(option.after.left) })}</p>
        </>
      )}
      <p className="hint row"><Icon name="info" size={16} />{t("rv_sens_note")}</p>
    </div>
  );
}

function thresholdText(th: NonNullable<NonNullable<PriceOption["sensitivity"]>["threshold"]>, option: PriceOption, i18n: I18n) {
  const full = optionName(option.id, i18n);
  const name = full.charAt(0).toLowerCase() + full.slice(1);   // used mid-sentence
  if (th.decline !== null) {
    // Shown to one decimal: exact value stays on the server.
    return i18n.t("rv_threshold", { option: name, pct: i18n.pctPoints(Math.round(th.decline * 1000) / 10) });
  }
  return i18n.t(`rv_threshold_${th.reason}` as Key, { option: name });
}

/** Held dish: no price options and no AI review until the owner confirms the missing input. */
export function HeldOptions({ dish }: { dish: Dish }) {
  const { view, i18n } = useApp();
  const { t } = i18n;
  const lines = view.report.needs_input.filter((n) => n.kind === "line_review" && n.dishes?.includes(dish.id));
  if (!lines.length) return null;
  return (
    <section className="rec-block stack" aria-label={t("rv_open")}>
      <h4>{t("rv_held_title")}</h4>
      <ul className="proposal-facts">
        {lines.map((l) => (
          <li key={`${l.invoice_id}-${l.line_id}`}><Icon name="pause" size={18} />
            <span>{t("rv_held_line", { original: l.original, no: l.invoice_no,
              reasons: l.reasons.map((r: string) => t(`reason_${r}` as Key)).join(" ") })}</span></li>
        ))}
      </ul>
      <p className="hint">{t("rv_held_why", { dish: dishName(view, dish.id, i18n) })}</p>
      <a href="#/invoices">{t("review_now")} <Icon name="chevron" size={16} /></a>
      <Investigator dish={dish} />
    </section>
  );
}
