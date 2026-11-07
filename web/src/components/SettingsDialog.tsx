// Small settings panel: DoorDash commission, packaging, target margin, monthly orders,
// plus the fixed trust rules (what Night Shift does alone vs. asks you).

import { useId, useState } from "react";
import { api } from "../api";
import { useApp } from "../context";
import { errorText, fieldError, fieldErrors } from "../format";
import { Dialog } from "./Dialog";
import { Icon } from "./Icon";

export function SettingsDialog({ onClose }: { onClose: () => void }) {
  const { view, setView, i18n, announce } = useApp();
  const { t } = i18n;
  const s = view.settings;
  const [commission, setCommission] = useState(String(s.commission_pct));
  const [packaging, setPackaging] = useState(s.packaging.toFixed(2));
  const [target, setTarget] = useState(String(s.target_margin_pct));
  const [orders, setOrders] = useState<Record<string, string>>(
    Object.fromEntries(Object.entries(s.monthly_orders).map(([k, v]) => [k, String(v)])));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const id = useId();

  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      const r = await api.saveSettings({
        commission_pct: commission, packaging: packaging.replace(",", "."), target_margin_pct: target.replace(",", "."),
        monthly_orders: orders,
      });
      setView(r.view);
      announce(t("s_saved"));
      onClose();
    } catch (err) {
      const fields = fieldErrors(err);
      setErrors(fields);
      setFormError(Object.keys(fields).length ? null : errorText(err, i18n));
      const first = Object.keys(fields)[0];
      if (first) document.getElementById(`${id}-${first}`)?.focus();
    }
  }

  const described = (name: string) => (errors[name] ? `${id}-${name}-err` : undefined);
  const errorFor = (name: string) =>
    errors[name] ? (
      <p id={`${id}-${name}-err`} className="field-error"><Icon name="alert" size={18} />{fieldError(errors[name], i18n)}</p>
    ) : null;

  return (
    <Dialog open title={t("settings_title")} onClose={onClose} closeLabel={t("close")}>
      <form className="stack" onSubmit={save} noValidate>
        <fieldset>
          <legend>{t("s_commission")}</legend>
          <div className="row">
            {view.commission_choices.map((c, i) => (
              <label key={c} className="choice">
                <input id={i === 0 ? `${id}-commission_pct` : undefined} type="radio" name="commission"
                  value={c} checked={commission === String(c)} onChange={() => setCommission(String(c))} />
                {i18n.pctPoints(c)}
              </label>
            ))}
          </div>
          {errorFor("commission_pct")}
        </fieldset>

        <div className="field">
          <label htmlFor={`${id}-packaging`}>{t("s_packaging")}</label>
          <input id={`${id}-packaging`} type="text" inputMode="decimal" value={packaging}
            onChange={(e) => setPackaging(e.target.value)} aria-invalid={!!errors.packaging}
            aria-describedby={described("packaging")} />
          {errorFor("packaging")}
        </div>

        <div className="field">
          <label htmlFor={`${id}-target_margin_pct`}>{t("s_target")}</label>
          <p className="hint" id={`${id}-target-hint`}>{t("s_target_hint")}</p>
          <input id={`${id}-target_margin_pct`} type="text" inputMode="decimal" value={target}
            onChange={(e) => setTarget(e.target.value)} aria-invalid={!!errors.target_margin_pct}
            aria-describedby={[`${id}-target-hint`, described("target_margin_pct")].filter(Boolean).join(" ")} />
          {errorFor("target_margin_pct")}
        </div>

        <fieldset>
          <legend>{t("s_orders")}</legend>
          <div className="orders-grid">
            {view.dishes.map((d) => (
              <div className="field" key={d.id}>
                <label htmlFor={`${id}-orders_${d.id}`}>{i18n.name(d.name)}</label>
                <input id={`${id}-orders_${d.id}`} type="text" inputMode="numeric" value={orders[d.id] ?? ""}
                  onChange={(e) => setOrders({ ...orders, [d.id]: e.target.value })}
                  aria-invalid={!!errors[`orders_${d.id}`]} aria-describedby={described(`orders_${d.id}`)} />
                {errorFor(`orders_${d.id}`)}
              </div>
            ))}
          </div>
        </fieldset>

        {formError && <p className="field-error"><Icon name="alert" size={18} />{formError}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>{t("cancel")}</button>
          <button type="submit" className="btn btn-primary"><Icon name="check" />{t("save")}</button>
        </div>
      </form>

      <section className="trust-rules" aria-labelledby={`${id}-trust`}>
        <h3 id={`${id}-trust`}>{t("trust_title")}</h3>
        <dl>
          <div><dt><Icon name="sparkle" size={18} />{t("trust_auto")}</dt><dd>{t("trust_auto_body")}</dd></div>
          <div><dt><Icon name="eye" size={18} />{t("trust_review")}</dt><dd>{t("trust_review_body")}</dd></div>
          <div><dt><Icon name="shield" size={18} />{t("trust_approve")}</dt><dd>{t("trust_approve_body")}</dd></div>
        </dl>
      </section>
    </Dialog>
  );
}
