// Invoice Review: each printed line, what Night Shift extracted, and the normalized cost.
// Unclear lines say "Needs review", show the invoice image cropped to that line, and hold their dishes
// until the owner confirms. Skipped duplicates are listed with their evidence.

import { useId, useState } from "react";
import { api, type Invoice, type InvoiceLine, type PossibleCorrection } from "../api";
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
  const inputId = useId(), messageId = useId(), cameraId = useId();

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
        {/* Phones and tablets open the rear camera; desktops fall back to choosing a file. */}
        <div className="row">
          <label htmlFor={cameraId} className="btn">
            <Icon name="upload" />{t("inv_camera")}
            <input id={cameraId} type="file" accept="image/*" capture="environment" className="sr-only"
              aria-describedby={message ? messageId : undefined}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) send(f, f.name || "photo.jpg"); e.target.value = ""; }} />
          </label>
        </div>
        {message && <p id={messageId} className="notice warn"><Icon name="alert" size={18} />{message}</p>}
        <div className="sample-invoices">
          <p><strong>{t("inv_sample_title")}</strong> {t("inv_sample_hint")}</p>
          <ul className="row">
            <li><a href="/samples/test_invoice_northbank_NB-7731.png" download><Icon name="download" size={16} />{t("inv_sample_png")}</a></li>
            <li><a href="/samples/test_invoice_northbank_NB-7731_phone_photo.jpg" download><Icon name="download" size={16} />{t("inv_sample_photo")}</a></li>
          </ul>
        </div>
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

      {view.possible_corrections.map((pc) => <PossibleCorrectionCard key={pc.id} pc={pc} />)}

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
  const { view } = useApp();
  const counted = invoice.superseded_by === null;
  const review = counted ? invoice.lines.filter((l) => l.status === "needs_review").length : 0;
  const fileOf = (id: number | null) => view.invoices.find((i) => i.id === id)?.file ?? "";
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
        {counted && (
          <span className={`pill ${review ? "warn" : "good"}`}>
            <Icon name={review ? "eye" : "checkCircle"} size={16} />
            {t("inv_counts", { verified: num(invoice.lines.length - review), review: num(review) })}
          </span>
        )}
      </div>
      <Provenance extraction={invoice.extraction} at={invoice.read_at} />
      {!counted && <p className="notice"><Icon name="minus" />{t("inv_superseded", { file: fileOf(invoice.superseded_by) })}</p>}
      {invoice.replaces !== null && <p className="notice"><Icon name="info" />{t("inv_replaces", { file: fileOf(invoice.replaces) })}</p>}
      <p className={invoice.totals_match ? "row text-good" : "notice warn"} style={{ gap: 8 }}>
        <Icon name={invoice.totals_match ? "checkCircle" : "alert"} size={18} />
        <span>{rich(invoice.totals_match ? "totals_ok" : "totals_bad", {
          sum: <Num source={sumSource}>{money(invoice.lines_sum)}</Num>,
          total: invoice.total == null ? "—" : <Num source={totalSource}>{money(invoice.total)}</Num>,
        })}</span>
      </p>
      <ol className="line-list" aria-label={t("inv_lines")}>
        {/* Lines needing review first: that's where the owner's attention goes. */}
        {[...invoice.lines].sort((a, b) => Number(b.status === "needs_review") - Number(a.status === "needs_review"))
          .map((line) => <LineCard key={line.id} invoice={invoice} line={line} counted={counted} />)}
      </ol>
    </section>
  );
}

function LineCard({ invoice, line, counted }: { invoice: Invoice; line: InvoiceLine; counted: boolean }) {
  const { view, i18n } = useApp();
  const { t, money, num, name } = i18n;
  const [editing, setEditing] = useState(false);
  const needsReview = counted && line.status === "needs_review";
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
      {counted && (
        <div className="row">
          <button type="button" className={needsReview ? "btn btn-primary" : "btn"} onClick={() => setEditing(true)}
            aria-label={t(needsReview ? "fix_aria" : "check_aria", { original: line.original })}>
            <Icon name="edit" />{needsReview ? t("fix_line") : t("check_line")}
          </button>
        </div>
      )}
      {editing && <CorrectLineDialog invoice={invoice} line={line} onClose={() => setEditing(false)} />}
    </li>
  );
}

/** Where the reading came from: the model just now, or a stored reading (no AI call). Never blurred together. */
export function Provenance({ extraction, at }: { extraction: "ai" | "saved"; at: string }) {
  const { i18n } = useApp();
  const { t } = i18n;
  if (extraction === "saved") {
    return <p className="row hint" style={{ gap: 8 }}><span className="pill neutral prov"><Icon name="refresh" size={16} />{t("prov_saved")}</span>
      {t("prov_saved_hint")}</p>;
  }
  const recent = Date.now() - new Date(at).getTime() < 10 * 60 * 1000;
  return <p className="row"><span className="pill neutral prov"><Icon name="eye" size={16} />
    {recent ? t("prov_ai") : t("prov_ai_at", { time: `${i18n.day(at.slice(0, 10))} ${i18n.time(at)}` })}</span></p>;
}

/** Same supplier + invoice number as a counted invoice, different contents: the owner picks which version counts. */
function PossibleCorrectionCard({ pc }: { pc: PossibleCorrection }) {
  const { setView, i18n, announce } = useApp();
  const { t, money, num } = i18n;
  const [busy, setBusy] = useState(false);
  const headingId = `pc-${pc.id}`;
  const lineText = (l: PossibleCorrection["only_new"][number]) => t("pc_line", {
    original: l.original, qty: l.quantity == null ? "—" : num(l.quantity), price: l.pack_price == null ? "—" : money(l.pack_price) });

  async function choose(choice: "keep_original" | "use_new") {
    setBusy(true);
    try {
      setView((await api.resolveCorrection(pc.id, choice)).view);
      announce(t(choice === "use_new" ? "pc_used_announce" : "pc_kept_announce", { no: pc.invoice_no }));
    } catch (e) {
      announce(errorText(e, i18n));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section id={`correction-${pc.id}`} className="card stack" aria-labelledby={headingId} tabIndex={-1}>
      <div className="card-head">
        <div>
          <h2 id={headingId}>{t("pc_title")}: {pc.supplier} {pc.invoice_no}</h2>
          <p className="hint">{t("n_possible_correction_ev", { file: pc.file, of_file: pc.of_file,
            total: pc.total == null ? "—" : money(pc.total), of_total: pc.of_total == null ? "—" : money(pc.of_total) })}</p>
        </div>
        <span className="pill warn"><Icon name="eye" size={16} />{t("status_review")}</span>
      </div>
      <Provenance extraction={pc.extraction} at={pc.read_at} />
      <ul className="proposal-facts">
        <li><Icon name="checkCircle" size={18} /><span>{t("pc_counted", { file: pc.of_file,
          total: pc.of_total == null ? "—" : money(pc.of_total), lines: num(pc.of_lines) })}</span></li>
        <li><Icon name="receipt" size={18} /><span>{t("pc_new", { file: pc.file,
          total: pc.total == null ? "—" : money(pc.total), lines: num(pc.lines) })}</span></li>
      </ul>
      {pc.only_counted.length > 0 && <div><h3 className="hint">{t("pc_only_counted")}</h3>
        <ul className="pc-diff">{pc.only_counted.map((l, i) => <li key={i}>{lineText(l)}</li>)}</ul></div>}
      {pc.only_new.length > 0 && <div><h3 className="hint">{t("pc_only_new")}</h3>
        <ul className="pc-diff">{pc.only_new.map((l, i) => <li key={i}>{lineText(l)}</li>)}</ul></div>}
      <div className="row">
        <button type="button" className="btn" disabled={busy} onClick={() => choose("keep_original")}>
          <Icon name="check" />{t("pc_keep")}</button>
        <button type="button" className="btn btn-primary" disabled={busy} onClick={() => choose("use_new")}>
          <Icon name="refresh" />{t("pc_use_new")}</button>
      </div>
    </section>
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
