// One dish that needs a price decision. Three action choices:
//   Review supplier change · Compare price scenario · Dismiss with reason.
// Approving a scenario only saves it to the decision log; Night Shift never changes DoorDash.

import { useEffect, useId, useRef, useState } from "react";
import { api, type Dish } from "../api";
import { focusLater, useApp } from "../context";
import { dishStatus, errorText, fieldError, fieldErrors, packText, reasonText } from "../format";
import type { Key } from "../i18n";
import {
  breakdownSources, costChangeSource, invoiceSource, monthlySource, ordersSource, pctChangeSource,
  perOrderSource, targetSource,
} from "../sources";
import { Dialog } from "./Dialog";
import { Icon } from "./Icon";
import { AuthImage } from "./AuthImage";
import { Num } from "./Num";

const UNDO_SECONDS = 10;
type Panel = "supplier" | "scenario" | null;

export function RecommendationCard({ dish }: { dish: Dish }) {
  const { view, setView, i18n, announce } = useApp();
  const { t, rich, money, approx, pctPoints, name } = i18n;
  const [panel, setPanel] = useState<Panel>(null);
  const [justSaved, setJustSaved] = useState(false);
  const [editing, setEditing] = useState(false);
  const [dismissing, setDismissing] = useState(false);
  const dishLabel = name(dish.name);
  const headingId = `rec-${dish.id}`;
  const status = dishStatus(dish, i18n);
  const p = dish.proposal;
  const s = view.settings;
  const change = view.changes.find((c) => c.dishes.includes(dish.id) && c.pct > 0);
  const now = breakdownSources(dish, dish.now, view, i18n);
  const before = breakdownSources(dish, dish.before, view, i18n);

  async function act(action: "approve" | "undo" | "restore") {
    try {
      const r = await api[action](dish.id);
      setView(r.view);
      if (action === "approve") {
        setJustSaved(true);
        announce(t("saved_announce", { dish: dishLabel, price: money(p!.price) }));
        focusLater(`undo-${dish.id}`);
      } else if (action === "undo") {
        setJustSaved(false);
        setPanel("scenario");
        announce(t("undone_announce", { dish: dishLabel }));
        focusLater(`approve-${dish.id}`);
      } else {
        announce(t("restored_announce", { dish: dishLabel }));
        focusLater(`act-scenario-${dish.id}`);
      }
    } catch (e) {
      announce(errorText(e, i18n));
    }
  }

  if (dish.decision === "dismissed") {
    return (
      <article className="card rec dismissed" aria-labelledby={headingId}>
        <div className="card-head">
          <h3 id={headingId}>{dishLabel}</h3>
          <span className="pill neutral"><Icon name="minus" size={16} />
            {t("dismissed_with", { reason: dish.dismiss_reason ? reasonText(dish.dismiss_reason.code, dish.dismiss_reason.note, i18n) : "" })}
          </span>
        </div>
        <div className="row">
          <button id={`restore-${dish.id}`} type="button" className="btn" onClick={() => act("restore")}>
            <Icon name="undo" />{t("restore")}
          </button>
        </div>
      </article>
    );
  }

  const record = dish.decision === "approved" ? dish.approval : null;
  const toggle = (which: Panel) => setPanel(panel === which ? null : which);

  return (
    <article className={`card rec ${record ? "approved" : ""}`} aria-labelledby={headingId}>
      <div className="card-head">
        <h3 id={headingId}>{dishLabel}</h3>
        <span className={`pill ${status.tone}`}><Icon name={status.icon} size={16} />{status.text}</span>
      </div>

      {change && (
        <p className="cause">
          <Icon name="up" size={18} />
          <span>
            {rich("change_line", {
              ingredient: name(view.ingredients[change.ingredient].name),
              old: <Num source={invoiceSource(change.prev_source, i18n)}>{money(change.prev.pack_price)}</Num>,
              new: <Num source={invoiceSource(change.source, i18n)}>{money(change.now.pack_price)}</Num>,
              pack: packText(change.now, i18n),
            })}{" "}
            <strong>({rich("change_up", { pct: <Num source={pctChangeSource(change.prev, change.now, i18n)}>{i18n.pct(change.pct)}</Num> })})</strong>
          </span>
        </p>
      )}

      <section className="rec-block" aria-labelledby={`${headingId}-effect`}>
        <h4 id={`${headingId}-effect`}>{t("financial_effect")}</h4>
        <p>
          <span className="label">{t("amount_left_short")}: </span>
          <strong>{rich("left_change", {
            before: <Num source={before.left}>{money(dish.before.left)}</Num>,
            now: <Num source={now.left}>{money(dish.now.left)}</Num>,
            pct: <Num source={now.margin_pct}>{pctPoints(dish.now.margin_pct)}</Num>,
            target: <Num source={targetSource(i18n)}>{pctPoints(s.target_margin_pct)}</Num>,
          })}</strong>
        </p>
        <p className={dish.cost_change_per_order < 0 ? "text-bad" : undefined}>
          {rich("cost_effect", {
            per_order: <Num source={costChangeSource(dish, i18n)}>{money(dish.cost_change_per_order, true)}</Num>,
            monthly: <Num source={monthlySource(dish.cost_change_per_order, dish, i18n)}>{approx(dish.cost_change_monthly)}</Num>,
            volume: t("volume_note"),
            orders: <Num source={ordersSource(dish, i18n)}>{i18n.num(dish.monthly_orders)}</Num>,
          })}
        </p>
      </section>

      {record ? (
        <div className="saved-box" role="group" aria-labelledby={`${headingId}-saved`}>
          <p id={`${headingId}-saved`} className="saved-title"><Icon name="checkCircle" />{t("saved_msg")}</p>
          <p>{t("raise_price", { from: money(record.from_price!), to: money(record.to_price!) })}</p>
          <p className="hint">{t("saved_at", { time: i18n.time(record.at) })}</p>
          {justSaved && (
            <UndoButton id={`undo-${dish.id}`} label={t("undo_aria", { dish: dishLabel })}
              text={(sec) => t("undo_seconds", { seconds: i18n.num(sec) })}
              onUndo={() => act("undo")}
              onExpire={() => {
                const hadFocus = document.activeElement?.id === `undo-${dish.id}`;
                setJustSaved(false);
                if (hadFocus) focusLater(headingId);
              }} />
          )}
        </div>
      ) : p && (
        <>
          <div className="choices" role="group" aria-label={t("proposed_action")}>
            <button id={`act-supplier-${dish.id}`} type="button" className="btn" aria-expanded={panel === "supplier"}
              aria-controls={`${headingId}-supplier`} onClick={() => toggle("supplier")}>
              <Icon name="receipt" />{t("act_review")}
            </button>
            <button id={`act-scenario-${dish.id}`} type="button" className="btn btn-primary" aria-expanded={panel === "scenario"}
              aria-controls={`${headingId}-scenario`} onClick={() => toggle("scenario")}>
              <Icon name="dollar" />{t("act_compare")}
            </button>
            <button type="button" className="btn btn-ghost" onClick={() => setDismissing(true)}>
              <Icon name="x" />{t("act_dismiss")}
            </button>
          </div>

          <section id={`${headingId}-supplier`} className="rec-block" hidden={panel !== "supplier"}
            aria-labelledby={`${headingId}-supplier-h`}>
            <h4 id={`${headingId}-supplier-h`}>{t("supplier_title")}</h4>
            {change?.has_image && (
              <AuthImage className="crop" src={api.lineImageUrl(change.invoice_id, change.line_id)}
                alt={t("crop_alt", { no: change.source.invoice_no, original: change.original })} />
            )}
            {change && (
              <ul className="proposal-facts">
                <li><Icon name="clock" size={18} /><span>{rich("supplier_last", {
                  no: change.prev_source.invoice_no, date: i18n.day(change.prev_source.date),
                  price: <Num source={invoiceSource(change.prev_source, i18n)}>{money(change.prev.pack_price)}</Num>,
                  pack: packText(change.prev, i18n) })}</span></li>
                <li><Icon name="up" size={18} /><span>{rich("supplier_this", {
                  no: change.source.invoice_no, date: i18n.day(change.source.date),
                  price: <Num source={invoiceSource(change.source, i18n)}>{money(change.now.pack_price)}</Num>,
                  pack: packText(change.now, i18n) })}</span></li>
              </ul>
            )}
            <a href="#/invoices">{t("open_invoice")} <Icon name="chevron" size={16} /></a>
          </section>

          <section id={`${headingId}-scenario`} className="rec-block proposal" hidden={panel !== "scenario"}
            aria-labelledby={`${headingId}-scenario-h`}>
            <h4 id={`${headingId}-scenario-h`}>{t("scenario_title")}</h4>
            <p className="hint">{rich("scenario_label", {
              orders: <Num source={ordersSource(dish, i18n)}>{i18n.num(dish.monthly_orders)}</Num> })}</p>
            <p className="proposal-line">{rich("scenario_price", {
              from: <Num source={now.price}>{money(dish.now.price)}</Num>,
              to: <Num source={breakdownSources(dish, p.after, view, i18n, p).price}>{money(p.price)}</Num> })}</p>
            <ul className="proposal-facts">
              <li><Icon name="checkCircle" size={18} /><span>{rich("scenario_left", {
                before: <Num source={now.left}>{money(dish.now.left)}</Num>,
                after: <Num source={breakdownSources(dish, p.after, view, i18n, p).left}>{money(p.after.left)}</Num>,
                pct: <Num source={breakdownSources(dish, p.after, view, i18n, p).margin_pct}>{pctPoints(p.after.margin_pct)}</Num> })}</span></li>
              <li><Icon name="dollar" size={18} /><strong>{rich("scenario_per_order", {
                change: <Num source={perOrderSource(dish, p, view, i18n)}>{money(p.per_order_change, true)}</Num> })}</strong></li>
              <li><Icon name="clock" size={18} /><strong>{rich("scenario_monthly", {
                monthly: <Num source={monthlySource(p.per_order_change, dish, i18n)}>{approx(p.monthly_change)}</Num> })}</strong></li>
            </ul>
            {p.edited && <p className="hint">{t("edited_note", { suggested: money(p.suggested) })}</p>}
            {!p.reaches_target && <p className="notice warn"><Icon name="alert" />{t("still_below")}</p>}
            <div className="actions">
              <button id={`approve-${dish.id}`} type="button" className="btn btn-primary btn-lg" onClick={() => act("approve")}
                aria-label={t("approve_aria", { dish: dishLabel, price: money(p.price) })}>
                <Icon name="check" />{t("approve_scenario")}
              </button>
              <button type="button" className="btn btn-lg" onClick={() => setEditing(true)}
                aria-label={t("edit_aria", { dish: dishLabel })}>
                <Icon name="edit" />{t("change_price")}
              </button>
            </div>
          </section>
        </>
      )}

      <div className="rec-foot">
        <a href={`#/dishes/${dish.id}`} aria-label={t("see_calc_for", { dish: dishLabel })}>
          {t("see_calc")} <Icon name="chevron" size={16} />
        </a>
        <span className="hint"><Icon name="info" size={16} />{t("excluded")}</span>
      </div>

      {editing && p && <EditPriceDialog dish={dish} onClose={() => setEditing(false)} />}
      {dismissing && <DismissDialog dish={dish} onClose={() => setDismissing(false)} />}
    </article>
  );
}

/** Undo for 10 seconds after approving. The countdown is visible; the accessible name stays stable. */
function UndoButton({ id, label, text, onUndo, onExpire }: {
  id: string; label: string; text: (seconds: number) => string; onUndo: () => void; onExpire: () => void;
}) {
  const [left, setLeft] = useState(UNDO_SECONDS);
  const expire = useRef(onExpire);
  expire.current = onExpire;
  useEffect(() => {
    const timer = window.setInterval(() => setLeft((sec) => sec - 1), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => { if (left <= 0) expire.current(); }, [left]);
  return (
    <button id={id} type="button" className="btn" aria-label={label} onClick={onUndo}>
      <Icon name="undo" />{text(Math.max(0, left))}
    </button>
  );
}

/** Dismissing needs a reason; "Other" needs a short note. Both are saved to the decision log. */
function DismissDialog({ dish, onClose }: { dish: Dish; onClose: () => void }) {
  const { view, setView, i18n, announce } = useApp();
  const { t, name } = i18n;
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const id = useId();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    try {
      setView((await api.dismiss(dish.id, reason, note)).view);
      announce(t("dismissed_announce", { dish: name(dish.name) }));
      onClose();
      focusLater(`restore-${dish.id}`);
    } catch (err) {
      const f = fieldErrors(err);
      setErrors(Object.keys(f).length ? f : { form: errorText(err, i18n) });
      document.getElementById(f.note ? `${id}-note` : `${id}-reason-0`)?.focus();
    }
  }

  return (
    <Dialog open title={t("dismiss_title", { dish: name(dish.name) })} onClose={onClose} closeLabel={t("close")}>
      <form className="stack" onSubmit={submit} noValidate>
        <fieldset aria-describedby={errors.reason ? `${id}-reason-err` : undefined}>
          <legend>{t("dismiss_legend")}</legend>
          {view.dismiss_reasons.map((code, i) => (
            <label key={code} className="radio-card">
              <input id={`${id}-reason-${i}`} type="radio" name={`${id}-reason`} value={code}
                checked={reason === code} onChange={() => setReason(code)} />
              <span>{t(`reason_${code}` as Key)}</span>
            </label>
          ))}
          {errors.reason && <p id={`${id}-reason-err`} className="field-error"><Icon name="alert" size={18} />{fieldError(errors.reason, i18n)}</p>}
        </fieldset>
        {reason === "other" && (
          <div className="field">
            <label htmlFor={`${id}-note`}>{t("dismiss_note")}</label>
            <input id={`${id}-note`} type="text" value={note} maxLength={200} onChange={(e) => setNote(e.target.value)}
              aria-invalid={!!errors.note} aria-describedby={errors.note ? `${id}-note-err` : undefined} />
            {errors.note && <p id={`${id}-note-err`} className="field-error"><Icon name="alert" size={18} />{fieldError(errors.note, i18n)}</p>}
          </div>
        )}
        {errors.form && <p className="field-error"><Icon name="alert" size={18} />{errors.form}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>{t("cancel")}</button>
          <button type="submit" className="btn btn-danger"><Icon name="x" />{t("dismiss_confirm")}</button>
        </div>
      </form>
    </Dialog>
  );
}

/** Change the scenario price; the server recomputes the result as you type. */
function EditPriceDialog({ dish, onClose }: { dish: Dish; onClose: () => void }) {
  const { setView, i18n, announce } = useApp();
  const { t, money, approx, pctPoints, name } = i18n;
  const [value, setValue] = useState(dish.proposal!.price.toFixed(2));
  const [preview, setPreview] = useState(dish.proposal);
  const [error, setError] = useState<string | null>(null);
  const inputId = useId(), errorId = useId(), previewId = useId(), hintId = useId();
  const normalized = value.trim().replace(/[$\s]/g, "").replace(",", ".");

  useEffect(() => {
    const timer = window.setTimeout(async () => {
      try {
        setPreview((await api.preview(dish.id, normalized)).proposal);
        setError(null);
      } catch (e) {
        setPreview(null);
        setError(errorText(e, i18n));
      }
    }, 300);
    return () => window.clearTimeout(timer);
  }, [normalized, dish.id, i18n]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      setView((await api.setProposal(dish.id, normalized)).view);
      announce(t("saved"));
      onClose();
    } catch (err) {
      setError(errorText(err, i18n));
      document.getElementById(inputId)?.focus();
    }
  }

  return (
    <Dialog open title={t("edit_title", { dish: name(dish.name) })} onClose={onClose} closeLabel={t("close")}>
      <form className="stack" onSubmit={save} noValidate>
        <div className="field">
          <label htmlFor={inputId}>{t("edit_label")}</label>
          <p id={hintId} className="hint">{t("edit_hint", { price: money(dish.now.price) })}</p>
          <input id={inputId} type="text" inputMode="decimal" autoComplete="off" value={value}
            onChange={(e) => setValue(e.target.value)} aria-invalid={!!error}
            aria-describedby={[hintId, error ? errorId : previewId].join(" ")} />
          {error && <p id={errorId} className="field-error"><Icon name="alert" size={18} />{error}</p>}
        </div>
        {preview && !error && (
          <p id={previewId} className={preview.reaches_target ? "text-good row" : "text-warn row"} style={{ gap: 8 }}>
            <Icon name={preview.reaches_target ? "checkCircle" : "alert"} />
            {t("edit_preview", {
              left: money(preview.after.left), pct: pctPoints(preview.after.margin_pct),
              monthly: approx(preview.monthly_change), volume: t("volume_note"),
            })}
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>{t("cancel")}</button>
          <button type="submit" className="btn btn-primary"><Icon name="check" />{t("edit_save")}</button>
        </div>
      </form>
    </Dialog>
  );
}
