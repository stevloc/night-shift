// "Review my options": a compact panel in the dish's decision area.
//   1. Code compares the options (keep / suggested / your price / your limit) from the server snapshot.
//   2. Optionally, ONE AI decision review explains them against what the owner said.
// Every figure comes from the server snapshot, never from the AI. The review changes nothing:
// the owner still decides with Approve / Change price / Keep / Dismiss above.

import { useEffect, useId, useMemo, useState } from "react";
import { api, type DecisionReview, type Dish, type Evidence, type Limits, type OptionId, type PriceOption,
  type ReviewResult, type Snapshot } from "../api";
import { useApp } from "../context";
import { dishName, errorText, fieldError, fieldErrors, ingredientName } from "../format";
import type { I18n, Key } from "../i18n";
import { Icon } from "./Icon";

const CATEGORY_ORDER = ["cost", "customer", "data_quality"] as const;

export function OptionsReview({ dish }: { dish: Dish }) {
  const { view, i18n, announce } = useApp();
  const { t } = i18n;
  const id = useId();
  const [open, setOpen] = useState(false);
  const [limits, setLimits] = useState<Limits>({ max_price: "", max_increase: "" });
  const [note, setNote] = useState("");
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ReviewResult | null>(null);
  const [resultContext, setResultContext] = useState("");
  const [loading, setLoading] = useState(false);
  const [focus, setFocus] = useState<OptionId | null>(null);
  const context = JSON.stringify({ note: note.trim(), ...limits });

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

  async function requestReview() {
    if (!snap) return;
    setLoading(true);
    try {
      const r = await api.review(dish.id, { ...limits, note, snapshot_version: snap.version, lang: i18n.lang });
      setResult(r);
      setResultContext(context);
      setSnap(r.snapshot);
      announce(r.status === "ok" ? t("rv_ready") : t("rv_not_ready"));
    } catch (e) {
      const f = fieldErrors(e);
      setErrors(Object.keys(f).length ? f : { form: errorText(e, i18n) });
    } finally {
      setLoading(false);
    }
  }

  const priced = snap?.options.filter((o) => o.id !== "keep_current") ?? [];
  const shown = priced.find((o) => o.id === focus) ?? priced.find((o) => o.id === "custom")
    ?? priced.find((o) => o.id === "limit") ?? priced[0];
  // A review is stale when the numbers or the owner's input changed since it was written.
  const stale = !!result && !!snap && result.status === "ok"
    && (result.snapshot.version !== snap.version || resultContext !== context);

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
            <OptionCards snap={snap} recommended={result?.status === "ok" && !stale ? result.review?.recommended_option_id ?? null : null} />
            {snap.conflicts.map((c) => (
              <p key={c.kind} className="notice warn"><Icon name="alert" />
                {t(c.best_reaches_target ? "rv_conflict_ok" : "rv_conflict", {
                  limit: i18n.money(c.limit), target_price: i18n.money(c.target_price),
                  pct: i18n.pctPoints(c.best_margin), target: i18n.pctPoints(snap.settings.target_margin_pct) })}</p>
            ))}
            {shown && <SensitivityTable snap={snap} option={shown} options={priced} onPick={setFocus} />}
            <p className="hint row"><Icon name="info" size={16} />{t("excluded")}</p>

            <div className="ai-review stack">
              <div className="row">
                <button type="button" className="btn btn-primary" onClick={requestReview} disabled={loading || !snap}>
                  {loading ? <span className="spinner" aria-hidden="true" /> : <Icon name="sparkle" />}
                  {t(result?.status === "ok" ? "rv_again" : "rv_request")}
                </button>
                <span className="hint">{t("rv_request_hint")}</span>
              </div>
              {loading && <p role="status" className="hint">{t("rv_loading")}</p>}
              {result && !loading && <ReviewOutcome result={result} snap={snap} stale={stale} />}
            </div>
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
function OptionCards({ snap, recommended }: { snap: Snapshot; recommended: OptionId | null }) {
  const { i18n } = useApp();
  const { t, money, pctPoints, approx } = i18n;
  return (
    <ul className="option-cards" aria-label={t("rv_options")}>
      {snap.options.map((o) => (
        <li key={o.id} className={recommended === o.id ? "recommended" : undefined}>
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
          {recommended === o.id && <span className="pill good"><Icon name="check" size={16} />{t("rv_suggested_by_review")}</span>}
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

function ReviewOutcome({ result, snap, stale }: { result: ReviewResult; snap: Snapshot; stale: boolean }) {
  const { i18n } = useApp();
  const { t } = i18n;
  if (result.status === "unavailable") {
    return (
      <p className="notice"><Icon name="info" />
        {t(`rv_unavailable_${result.reason ?? "provider_error"}` as Key, { minutes: i18n.num(result.retry_minutes ?? 60) })}
        {" "}{t("rv_unavailable_tail")}</p>
    );
  }
  if (result.status === "stale") return <p className="notice warn"><Icon name="refresh" />{t("rv_stale_discarded")}</p>;
  if (result.status === "held") return <p className="notice warn"><Icon name="pause" />{t("rv_held")}</p>;
  if (result.status === "no_options") return <p className="notice"><Icon name="info" />{t("rv_no_options")}</p>;
  return <ReviewBody review={result.review!} result={result} snap={snap} stale={stale} />;
}

function ReviewBody({ review, result, snap, stale }: { review: DecisionReview; result: ReviewResult; snap: Snapshot; stale: boolean }) {
  const { i18n } = useApp();
  const { t, money, pctPoints } = i18n;
  const evidence = useMemo(() => new Map(result.snapshot.evidence.map((e) => [e.id, e])), [result.snapshot]);
  // Figures for the suggested option come from the snapshot the review was written for.
  const rec = result.snapshot.options.find((o) => o.id === review.recommended_option_id);
  return (
    <article className={`review-result stack ${stale ? "is-stale" : ""}`} aria-labelledby="review-h">
      <div className="card-head">
        <h5 id="review-h">{t("rv_title")}</h5>
        <span className="pill neutral"><Icon name={result.provenance === "live" ? "sparkle" : "clock"} size={16} />
          {result.provenance === "live" ? t("rv_live", { model: result.model ?? "" })
            : t("rv_cached", { time: i18n.time(result.generated_at!) })}</span>
      </div>
      {stale && <p className="notice warn"><Icon name="refresh" />{t("rv_stale")}</p>}
      {rec ? (
        <p><strong>{t("rv_recommended", { option: optionName(rec.id, i18n), price: money(rec.price),
          left: money(rec.after.left), pct: pctPoints(rec.after.margin_pct) })}</strong></p>
      ) : <p><strong>{t("rv_no_recommendation")}</strong></p>}
      <p>{review.summary}</p>
      {CATEGORY_ORDER.map((cat) => {
        const items = review.considerations.filter((c) => c.category === cat);
        if (!items.length) return null;
        return (
          <div key={cat} className="stack-sm">
            <h6>{t(`rv_cat_${cat}` as Key)}</h6>
            <ul className="review-points">
              {items.map((c, i) => (
                <li key={i}>
                  <p>{c.basis === "owner_reported" && <span className="tag">{t("rv_you_said")}</span>}{c.text}</p>
                  <EvidenceLinks ids={c.evidence_ids} evidence={evidence} />
                </li>
              ))}
            </ul>
          </div>
        );
      })}
      {review.uncertainties.length > 0 && (
        <div className="stack-sm">
          <h6>{t("rv_uncertain")}</h6>
          <ul className="review-points">
            {review.uncertainties.map((u, i) => (
              <li key={i}><p>{u.text}</p><EvidenceLinks ids={u.evidence_ids} evidence={evidence} /></li>
            ))}
          </ul>
        </div>
      )}
      {review.follow_up_question && <p><strong>{t("rv_question")}</strong> {review.follow_up_question}</p>}
      {review.next_action && <p><strong>{t("rv_next")}</strong> {t(`action_${review.next_action}` as Key)}</p>}
      <p className="hint row"><Icon name="info" size={16} />{t("rv_changes_nothing")}</p>
      {snap.version !== result.snapshot.version && <p className="hint">{t("rv_version_note")}</p>}
    </article>
  );
}

function EvidenceLinks({ ids, evidence }: { ids: string[]; evidence: Map<string, Evidence> }) {
  const { view, i18n } = useApp();
  if (!ids.length) return null;
  return (
    <ul className="evidence-links" aria-label={i18n.t("rv_evidence")}>
      {ids.map((eid) => {
        const e = evidence.get(eid);
        if (!e) return null;
        const label = evidenceLabel(e, view, i18n);
        const prov = i18n.t(`evp_${e.provenance}` as Key);
        return (
          <li key={eid} title={e.text}>
            {e.link ? <a href={e.link}>{label}</a> : <span>{label}</span>}
            <span className="hint"> · {prov}</span>
          </li>
        );
      })}
    </ul>
  );
}

function evidenceLabel(e: Evidence, view: ReturnType<typeof useApp>["view"], i18n: I18n) {
  const { t } = i18n;
  const [kind, rest] = [e.id.split(":")[0], e.id.split(":")[1]];
  const ing = e.ingredient ? ingredientName(view, e.ingredient, i18n) : "";
  switch (kind) {
    case "cost": return t("evd_cost", { ingredient: ing, no: e.invoice_no ?? "" });
    case "comparison": return t("evd_comparison", { ingredient: ing, no: e.invoice_no ?? "" });
    case "earlier": return t("evd_earlier", { ingredient: ing, no: e.invoice_no ?? "" });
    case "hold": return t("evd_hold", { ingredient: ing });
    case "correction": return t("evd_correction", { no: e.invoice_no ?? "" });
    case "conflict": return t("evd_conflict");
    case "option": return optionName(rest as OptionId, i18n);
    default: return t(`evd_${e.id.replace(":", "_")}` as Key);
  }
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
    </section>
  );
}
