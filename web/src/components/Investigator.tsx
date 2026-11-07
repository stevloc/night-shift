// "Investigate this alert": one bounded AI investigation for the selected dish.
// Shows only what actually happened: the tool checks the server ran, the validated finding, and
// scenario figures exactly as Night Shift's calculator returned them. It never changes anything.

import { useState } from "react";
import { api, type Dish, type InvestigationEvent, type InvestigationResult, type Limits } from "../api";
import { useApp } from "../context";
import { dishName, errorText, ingredientName } from "../format";
import type { Key } from "../i18n";
import { Icon } from "./Icon";

const NO_LIMITS: Limits = { max_price: "", max_increase: "" };
const STATUS_ICON = { ok: "check", held: "pause", missing: "alert", error: "x" } as const;

export function Investigator({ dish, limits = NO_LIMITS, note = "", version }: {
  dish: Dish; limits?: Limits; note?: string; version?: string;
}) {
  const { i18n, announce } = useApp();
  const { t } = i18n;
  const [result, setResult] = useState<InvestigationResult | null>(null);
  const [asked, setAsked] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const context = JSON.stringify({ note: note.trim(), ...limits, version });

  async function run() {
    setLoading(true);
    setError(null);
    try {
      const r = await api.investigate(dish.id, { ...limits, note, snapshot_version: version, lang: i18n.lang });
      setResult(r);
      setAsked(context);
      announce(r.status === "ok" ? t("inv_done") : t("inv_not_done"));
    } catch (e) {
      setError(errorText(e, i18n));
    } finally {
      setLoading(false);
    }
  }

  // Out of date when the numbers, the limit or the note changed after it ran.
  const stale = !!result && result.status === "ok" && asked !== context;

  return (
    <div className="ai-review stack">
      <div className="row">
        <button type="button" className="btn btn-primary" onClick={run} disabled={loading}>
          {loading ? <span className="spinner" aria-hidden="true" /> : <Icon name="sparkle" />}
          {t(result?.status === "ok" ? "inv_again" : "inv_button")}
        </button>
        <span className="hint">{t("inv_hint")}</span>
      </div>
      {loading && <p role="status" className="hint">{t("inv_loading")}</p>}
      {error && <p className="field-error"><Icon name="alert" size={18} />{error}</p>}
      {result && !loading && <Outcome result={result} dish={dish} stale={stale} />}
    </div>
  );
}

function Outcome({ result, dish, stale }: { result: InvestigationResult; dish: Dish; stale: boolean }) {
  const { i18n } = useApp();
  const { t, money, pctPoints, approx } = i18n;
  const f = result.finding;

  if (result.status === "stale") {
    return <p className="notice warn"><Icon name="refresh" />{t("inv_stale_discarded")}</p>;
  }
  const reason = result.status === "unavailable" && (
    <p className="notice"><Icon name="info" />
      {t(`inv_unavail_${result.reason ?? "provider_error"}` as Key, { minutes: i18n.num(result.retry_minutes ?? 60) })}
      {" "}{t("inv_unavail_tail")}</p>
  );
  if (!f) {
    return <div className="stack-sm">{reason}{result.events.length > 0 && <Activity events={result.events} dish={dish} />}</div>;
  }
  const tone = f.outcome === "ready_for_review" ? "good" : f.outcome === "needs_confirmation" ? "warn" : "neutral";
  return (
    <article className={`review-result stack ${stale ? "is-stale" : ""}`} aria-labelledby={`inv-${dish.id}`}>
      <div className="card-head">
        <h5 id={`inv-${dish.id}`}>{t("inv_title")}</h5>
        <span className={`pill ${tone}`}>
          <Icon name={tone === "good" ? "checkCircle" : tone === "warn" ? "pause" : "info"} size={16} />
          {t(`inv_outcome_${f.outcome}` as Key)}</span>
      </div>
      <p className="hint">{t("inv_live", { model: result.model ?? "", checks: i18n.num(result.tool_executions ?? 0),
        seconds: i18n.num(result.elapsed_seconds ?? 0) })}
        {result.readings?.length ? <> {t(result.readings.includes("ai")
          ? (result.readings.includes("saved") ? "inv_readings_mixed" : "inv_readings_ai") : "inv_readings_saved")}</> : null}</p>
      {stale && <p className="notice warn"><Icon name="refresh" />{t("inv_stale")}</p>}
      <Activity events={result.events} dish={dish} />
      <p>{f.summary}</p>
      {(result.scenarios ?? []).map((s) => (
        <p key={s.ref} className="rec-block">
          <strong>{t("inv_scenario", { price: money(s.price), left: money(s.left_per_order), pct: pctPoints(s.share_left_pct) })}</strong>{" "}
          <span className={s.reaches_target ? "text-good" : "text-warn"}>
            {t(s.reaches_target ? "rv_reaches" : "rv_below", { target: pctPoints(s.target_pct) })}</span>
          <span className="hint"> · {t("rv_change", { per: money(s.change_per_order_vs_today, true) })}
            {s.monthly_change_if_orders_unchanged !== null
              && <> · {t("rv_monthly", { monthly: approx(s.monthly_change_if_orders_unchanged) })}</>}
          </span>
        </p>
      ))}
      {f.evidence_refs.length > 0 && (
        <ul className="evidence-links" aria-label={t("rv_evidence")}>
          {f.evidence_refs.map((ref) => <RefLink key={ref} id={ref} result={result} />)}
        </ul>
      )}
      {f.uncertainty.length > 0 && (
        <div className="stack-sm">
          <h6>{t("rv_uncertain")}</h6>
          <ul className="review-points">{f.uncertainty.map((u, i) => <li key={i}>{u}</li>)}</ul>
        </div>
      )}
      {f.question && <p><strong>{t("rv_question")}</strong> {f.question}</p>}
      {f.next_step && <p><strong>{t("rv_next")}</strong> {t(`next_${f.next_step}` as Key)}</p>}
      <p className="hint row"><Icon name="info" size={16} />{t("inv_changes_nothing")}</p>
    </article>
  );
}

/** The checks the server actually ran, in order, with what each found. */
function Activity({ events, dish }: { events: InvestigationEvent[]; dish: Dish }) {
  const { view, i18n } = useApp();
  const { t } = i18n;
  return (
    <ol className="activity-list" aria-label={t("inv_activity")}>
      {events.map((e, i) => (
        <li key={i} className={`st-${e.status}`}>
          <Icon name={STATUS_ICON[e.status] ?? "info"} size={16} />
          <span>{t(`inv_ev_${e.tool}` as Key, {
            ingredient: e.ingredient ? ingredientName(view, e.ingredient, i18n).toLowerCase() : "",
            dish: dishName(view, e.dish ?? dish.id, i18n),
            price: e.price != null ? i18n.money(e.price) : "",
          })}{e.status !== "ok" && <span className="hint"> · {t(`inv_st_${e.status}` as Key)}</span>}</span>
        </li>
      ))}
    </ol>
  );
}

function RefLink({ id, result }: { id: string; result: InvestigationResult }) {
  const { view, i18n } = useApp();
  const r = result.refs?.[id];
  if (!r) return null;
  const label = i18n.t(`inv_ref_${r.kind}` as Key, {
    no: r.invoice_no ?? "", ingredient: r.ingredient ? ingredientName(view, r.ingredient, i18n) : "",
    date: r.date ? i18n.day(r.date) : "", dish: r.dish ? dishName(view, r.dish, i18n) : "" });
  const link = r.kind === "invoice" ? "#/invoices" : r.dish ? `#/dishes/${r.dish}` : "";
  return <li>{link ? <a href={link}>{label}</a> : <span>{label}</span>}</li>;
}
