// Invoice Review: each printed line, what Night Shift extracted, and the normalized cost.
// Unclear lines say "Needs review", show the invoice image cropped to that line, and hold their dishes
// until the owner confirms. Skipped duplicates are listed with their evidence.

import { useId, useState } from "react";
import { api, type Invoice, type InvoiceLine } from "../api";
import { focusLater, useApp, type Route } from "../context";
import { errorText, fieldError, fieldErrors, ingredientName } from "../format";
import type { Key } from "../i18n";
import { Dialog } from "../components/Dialog";
import { Icon } from "../components/Icon";
import { AuthImage, InvoiceLink } from "../components/AuthImage";
import { Num, type NumSource } from "../components/Num";

export function InvoiceReview(_: { route: Route }) {
  const { view, i18n, uploadInvoice, uploading, runNightShift, running } = useApp();
  const { t, money } = i18n;
  const [dragging, setDragging] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const inputId = useId(), messageId = useId();

  async function send(file: Blob, name: string) {
    setMessage(await uploadInvoice(file, name));
  }

  return (
    <div className="stack-lg">
      <div className="page-head">
        <h1 id="page-title" tabIndex={-1}>{t("nav_invoices")}</h1>
        <p>{t("inv_intro")}</p>
      </div>

      <section className="card stack" aria-labelledby="add-title">
        <h2 id="add-title">{t("inv_add")}</h2>
        {/* The label is the drop zone; the visually hidden file input keeps keyboard + screen reader support. */}
        <label htmlFor={inputId} className={`dropzone ${dragging ? "dragging" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const file = e.dataTransfer.files[0];
            if (file) send(file, file.name);
          }}>
          <Icon name="upload" size={32} />
          <span className="btn btn-primary"><Icon name="receipt" />{t("inv_choose")}</span>
          <span className="hint">{t("inv_drop")}</span>
          <input id={inputId} type="file" accept="image/png,image/jpeg,image/webp,application/pdf" className="sr-only"
            aria-describedby={message ? messageId : undefined}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) send(f, f.name); e.target.value = ""; }} />
        </label>
        {message && <p id={messageId} className="notice warn"><Icon name="alert" size={18} />{message}</p>}
        <p className="hint">{t("inv_reupload_hint")}</p>
        <div className="row">
          {!view.has_run && (
            <button type="button" className="btn" onClick={runNightShift} disabled={running}>
              <Icon name="moon" />{t("run_button")}
            </button>
          )}
          {(uploading || running) && <span className="row" role="status"><span className="spinner" />{t("reading")}</span>}
        </div>
      </section>

      {view.invoices.length === 0 ? (
        <div className="card empty"><span className="icon-big"><Icon name="receipt" size={40} /></span><p>{t("inv_empty")}</p></div>
      ) : [...view.invoices].reverse().map((inv) => <InvoiceCard key={inv.id} invoice={inv} />)}

      {view.duplicates.length > 0 && (
        <section className="card stack" aria-labelledby="dup-title">
          <h2 id="dup-title">{t("dup_title")}</h2>
          <ul className="wys-list">
            {view.duplicates.map((d, i) => (
              <li key={i}>
                <time dateTime={d.at}>{i18n.time(d.at)}</time>
                <div>
                  <p className="wys-title"><strong>{t("v_duplicate", { no: d.invoice_no })}</strong></p>
                  <p className="wys-evidence">{t("v_duplicate_ev", { file: d.file, supplier: d.supplier, no: d.invoice_no,
                    total: money(d.total), of_file: d.of_file, of_time: i18n.time(d.of_at) })}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function InvoiceCard({ invoice }: { invoice: Invoice }) {
  const { i18n } = useApp();
  const { t, num, rich, money } = i18n;
  const review = invoice.lines.filter((l) => l.status === "needs_review").length;
  const headingId = `inv-${invoice.id}`;
  const sumSource: NumSource = { kind: "calc", detail: t("v_totals_ev", {
    lines: num(invoice.lines.length), sum: money(invoice.lines_sum), total: invoice.total == null ? "—" : money(invoice.total) }) };
  const totalSource: NumSource = { kind: "invoice", detail: t("sd_printed_total", { no: invoice.invoice_no }) };
  return (
    <section className="card stack" aria-labelledby={headingId}>
      <div className="card-head">
        <div>
          <h2 id={headingId}>{invoice.supplier || t("inv_uploaded")}</h2>
          {invoice.invoice_no && <p className="hint">{t("inv_meta", { no: invoice.invoice_no, date: i18n.day(invoice.date) })} · {invoice.file}</p>}
        </div>
        <span className={`pill ${review ? "warn" : "good"}`}>
          <Icon name={review ? "eye" : "checkCircle"} size={16} />
          {t("inv_counts", { verified: num(invoice.lines.length - review), review: num(review) })}
        </span>
      </div>
      <p className={invoice.totals_match ? "row text-good" : "notice warn"} style={{ gap: 8 }}>
        <Icon name={invoice.totals_match ? "checkCircle" : "alert"} size={18} />
        <span>{rich(invoice.totals_match ? "totals_ok" : "totals_bad", {
          sum: <Num source={sumSource}>{money(invoice.lines_sum)}</Num>,
          total: invoice.total == null ? "—" : <Num source={totalSource}>{money(invoice.total)}</Num>,
        })}</span>
      </p>
      {invoice.used_fallback && <p className="notice"><Icon name="info" />{t("inv_fallback")}</p>}
      <ol className="line-list" aria-label={t("inv_lines")}>
        {/* Lines needing review first: that's where the owner's attention goes. */}
        {[...invoice.lines].sort((a, b) => Number(b.status === "needs_review") - Number(a.status === "needs_review"))
          .map((line) => <LineCard key={line.id} invoice={invoice} line={line} />)}
      </ol>
    </section>
  );
}

function LineCard({ invoice, line }: { invoice: Invoice; line: InvoiceLine }) {
  const { view, i18n } = useApp();
  const { t, money, num, name } = i18n;
  const [editing, setEditing] = useState(false);
  const needsReview = line.status === "needs_review";
  const held = line.ingredient ? view.dishes.filter((d) => d.held_by.includes(line.ingredient!)).map((d) => name(d.name)) : [];
  const n = line.normalized;
  const fromInvoice: NumSource = { kind: line.corrected ? "owner" : "invoice",
    detail: t("sd_invoice", { supplier: invoice.supplier, no: invoice.invoice_no, date: i18n.day(invoice.date), original: line.original }) };

  return (
    <li id={`line-${invoice.id}-${line.id}`} tabIndex={-1} className={`line-card ${needsReview ? "review" : ""}`}>
      <div className="card-head">
        <p className="original"><span className="sr-only">{t("as_printed")}: </span>“{line.original}”</p>
        {needsReview
          ? <span className="pill warn"><Icon name="eye" size={16} />{t("status_review")}</span>
          : <span className="pill good"><Icon name="checkCircle" size={16} />{line.corrected ? t("status_corrected") : t("status_verified")}</span>}
      </div>
      {needsReview && line.has_image && (
        <figure className="crop-figure">
          <AuthImage className="crop" src={api.lineImageUrl(invoice.id, line.id)}
            alt={t("crop_alt", { no: invoice.invoice_no, original: line.original })} />
          <figcaption><InvoiceLink invoiceId={invoice.id} getLink={api.invoiceImageLink}>
            {t("see_full_invoice")} <Icon name="external" size={16} /></InvoiceLink></figcaption>
        </figure>
      )}
      <dl className="facts">
        <div><dt>{t("matched")}</dt><dd>{ingredientName(view, line.ingredient, i18n)}</dd></div>
        <div><dt>{t("pack")}</dt><dd>{line.pack_size && line.pack_unit
          ? <Num source={fromInvoice}>{num(line.pack_size)} {i18n.unit(line.pack_unit, line.pack_size)}</Num>
          : <em>{t("not_found")}</em>}</dd></div>
        <div><dt>{t("pack_price")}</dt><dd>{line.pack_price
          ? <Num source={fromInvoice}>{money(line.pack_price)}</Num> : <em>{t("not_found")}</em>}</dd></div>
        {line.line_total !== null && line.quantity && line.pack_price && (
          <div><dt>{t("amount_col")}</dt><dd><Num source={{ kind: "calc", detail: t("sd_line_total", {
            qty: num(line.quantity), price: money(line.pack_price) }) }}>{money(line.line_total)}</Num></dd></div>
        )}
        <div><dt>{t("normalized")}</dt><dd>{n ? i18n.rich("normalized_value", {
          per: <Num source={{ kind: "calc", detail: t("sd_per_unit", { price: money(line.pack_price!), size: num(line.pack_size!) }) }}>
            {i18n.unitMoney(n.per_unit)}</Num>,
          usable: <Num source={{ kind: "calc", detail: t("sd_usable", { per_unit: i18n.unitMoney(n.per_unit), yield: i18n.pctPoints(n.yield_pct) }) }}>
            {i18n.unitMoney(n.usable_per_unit)}</Num>,
          unit: i18n.unit(n.unit),
          yield: <Num source={{ kind: "setting", detail: t("sd_yield", { ingredient: ingredientName(view, line.ingredient, i18n) }) }}>
            {i18n.pctPoints(n.yield_pct)}</Num>,
        }) : "—"}</dd></div>
        {line.change !== null && (
          <div><dt>{t("vs_last")}</dt><dd>{Math.abs(line.change) < 0.0005 ? t("same_as_last")
            : <span className={line.change > 0 ? "text-bad" : "text-good"}>
              {t(line.change > 0 ? "change_up" : "change_down", { pct: i18n.pct(line.change) })}</span>}</dd></div>
        )}
      </dl>
      {needsReview && (
        <div className="notice warn">
          <Icon name="alert" />
          <div>
            {line.reasons.map((r) => <p key={r}>{t(`reason_${r}` as Key)}</p>)}
            {held.length > 0 && <p><strong>{t("holds", { dishes: i18n.list(held) })}</strong></p>}
          </div>
        </div>
      )}
      <div className="row">
        <button type="button" className={needsReview ? "btn btn-primary" : "btn"} onClick={() => setEditing(true)}
          aria-label={t(needsReview ? "fix_aria" : "check_aria", { original: line.original })}>
          <Icon name="edit" />{needsReview ? t("fix_line") : t("check_line")}
        </button>
      </div>
      {editing && <CorrectLineDialog invoice={invoice} line={line} onClose={() => setEditing(false)} />}
    </li>
  );
}

/** Owner corrects or completes a line. For count items (sheets, each) the owner enters packs × items per pack. */
function CorrectLineDialog({ invoice, line, onClose }: { invoice: Invoice; line: InvoiceLine; onClose: () => void }) {
  const { view, setView, i18n, announce } = useApp();
  const { t, name, num } = i18n;
  const defaultUnit = line.pack_unit ?? (line.ingredient ? view.ingredients[line.ingredient].pack_unit : "");
  const [fields, setFields] = useState({
    ingredient: line.ingredient ?? "",
    pack_size: line.pack_size ? String(line.pack_size) : "",
    pack_unit: defaultUnit,
    pack_price: line.pack_price ? line.pack_price.toFixed(2) : "",
    packs: "",
    per_pack: "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const id = useId();
  const set = (k: keyof typeof fields) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setFields({ ...fields, [k]: e.target.value });
  const isCount = fields.pack_unit === "each" || fields.pack_unit === "sheet";
  const packs = Number(fields.packs.replace(",", ".")), perPack = Number(fields.per_pack.replace(",", "."));
  const caseTotal = isCount && packs > 0 && perPack > 0 ? packs * perPack : null;  // shown live; the server recomputes

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const body: Record<string, string> = {
      ingredient: fields.ingredient, pack_unit: fields.pack_unit,
      pack_price: fields.pack_price.replace(/[$\s]/g, "").replace(",", "."),
    };
    if (isCount) Object.assign(body, { packs: fields.packs, per_pack: fields.per_pack.replace(",", ".") });
    else body.pack_size = fields.pack_size.replace(",", ".");
    try {
      const r = await api.correctLine(invoice.id, line.id, body);
      setView(r.view);
      announce(t("line_saved"));
      onClose();
      focusLater(`line-${invoice.id}-${line.id}`);
    } catch (err) {
      const f = fieldErrors(err);
      setErrors(f);
      setFormError(Object.keys(f).length ? null : errorText(err, i18n));
      const first = ["ingredient", "packs", "per_pack", "pack_size", "pack_unit", "pack_price"].find((k) => f[k]);
      if (first) document.getElementById(`${id}-${first}`)?.focus();
    }
  }

  const describedBy = (k: string, extra?: string) =>
    [extra, errors[k] ? `${id}-${k}-err` : undefined].filter(Boolean).join(" ") || undefined;
  const errorFor = (k: string) => errors[k]
    ? <p id={`${id}-${k}-err`} className="field-error"><Icon name="alert" size={18} />{fieldError(errors[k], i18n)}</p> : null;
  const unitWord = (n: number) => i18n.unit(fields.pack_unit || "each", n);
  const capitalized = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

  return (
    <Dialog open title={t("line_title")} onClose={onClose} closeLabel={t("close")}>
      <p className="original">“{line.original}”</p>
      {line.has_image && <AuthImage className="crop" src={api.lineImageUrl(invoice.id, line.id)}
        alt={t("crop_alt", { no: invoice.invoice_no, original: line.original })} />}
      <form className="stack" onSubmit={save} noValidate>
        <div className="field">
          <label htmlFor={`${id}-ingredient`}>{t("f_ingredient")}</label>
          <select id={`${id}-ingredient`} value={fields.ingredient} onChange={set("ingredient")}
            aria-invalid={!!errors.ingredient} aria-describedby={describedBy("ingredient")}>
            <option value="">{t("f_choose")}</option>
            {Object.entries(view.ingredients).map(([k, v]) => <option key={k} value={k}>{name(v.name)}</option>)}
          </select>
          {errorFor("ingredient")}
        </div>
        <div className="field">
          <label htmlFor={`${id}-pack_unit`}>{t("f_pack_unit")}</label>
          <select id={`${id}-pack_unit`} value={fields.pack_unit} onChange={set("pack_unit")}
            aria-invalid={!!errors.pack_unit} aria-describedby={describedBy("pack_unit")}>
            <option value="">{t("f_choose")}</option>
            {view.units.map((u) => <option key={u} value={u}>{i18n.unit(u)}</option>)}
          </select>
          {errorFor("pack_unit")}
        </div>
        {isCount ? (
          <>
            <p id={`${id}-hint`} className="hint">{t("f_contents_hint")}</p>
            <div className="field-row">
              <div className="field">
                <label htmlFor={`${id}-packs`}>{t("f_packs")}</label>
                <input id={`${id}-packs`} type="text" inputMode="numeric" value={fields.packs} onChange={set("packs")} data-autofocus
                  aria-invalid={!!errors.packs} aria-describedby={describedBy("packs", `${id}-hint`)} />
                {errorFor("packs")}
              </div>
              <div className="field">
                <label htmlFor={`${id}-per_pack`}>{t("f_per_pack", { unit: capitalized(unitWord(2)) })}</label>
                <input id={`${id}-per_pack`} type="text" inputMode="numeric" value={fields.per_pack} onChange={set("per_pack")}
                  aria-invalid={!!errors.per_pack} aria-describedby={describedBy("per_pack", `${id}-hint`)} />
                {errorFor("per_pack")}
              </div>
            </div>
            <p className="case-total" aria-live="polite">
              {caseTotal !== null ? t("f_case_total", { size: num(caseTotal), unit: unitWord(caseTotal) }) : " "}
            </p>
          </>
        ) : (
          <div className="field">
            <label htmlFor={`${id}-pack_size`}>{t("f_pack_size")}</label>
            <input id={`${id}-pack_size`} type="text" inputMode="decimal" value={fields.pack_size} onChange={set("pack_size")}
              aria-invalid={!!errors.pack_size} aria-describedby={describedBy("pack_size")} />
            {errorFor("pack_size")}
          </div>
        )}
        <div className="field">
          <label htmlFor={`${id}-pack_price`}>{t("f_pack_price")}</label>
          <input id={`${id}-pack_price`} type="text" inputMode="decimal" value={fields.pack_price} onChange={set("pack_price")}
            aria-invalid={!!errors.pack_price} aria-describedby={describedBy("pack_price")} />
          {errorFor("pack_price")}
        </div>
        {formError && <p className="field-error"><Icon name="alert" size={18} />{formError}</p>}
        <div className="dialog-actions">
          <button type="button" className="btn" onClick={onClose}>{t("cancel")}</button>
          <button type="submit" className="btn btn-primary"><Icon name="check" />{t("save")}</button>
        </div>
      </form>
    </Dialog>
  );
}
