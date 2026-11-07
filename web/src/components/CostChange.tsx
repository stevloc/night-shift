// One ingredient's cost change, from the server's single cost record:
//   the cost in use now (and its invoice line) vs. the explicit comparison (before tonight's run).
// Earlier invoices stay visible as history, never labelled as the current price.

import type { Change } from "../api";
import { useApp } from "../context";
import { packText } from "../format";
import { invoiceSource, pctChangeSource } from "../sources";
import { Num } from "./Num";

export function CostChangeLine({ change, strong = false }: { change: Change; strong?: boolean }) {
  const { view, i18n } = useApp();
  const { rich, money, name, t } = i18n;
  const line = rich("change_line", {
    ingredient: name(view.ingredients[change.ingredient].name),
    old: <Num source={invoiceSource(change.comparison_source, i18n)}>{money(change.comparison.pack_price)}</Num>,
    new: <Num source={invoiceSource(change.current_source, i18n)}>{money(change.current.pack_price)}</Num>,
    pack: packText(change.current, i18n),
  });
  return (
    <>
      {strong ? <strong>{line}</strong> : line}{" "}
      <span className={change.pct > 0 ? "text-bad" : "text-good"}>
        ({rich(change.pct > 0 ? "change_vs_up" : "change_vs_down", {
          pct: <Num source={pctChangeSource(change.comparison, change.current, i18n)}>{i18n.pct(change.pct)}</Num>,
          basis: t(`basis_${change.comparison_basis}`),
        })})
      </span>
    </>
  );
}

/** "Earlier invoice RM-20419: $134.20 … historical, not the current price." */
export function EarlierInvoices({ change }: { change: Change }) {
  const { i18n } = useApp();
  if (!change.earlier.length) return null;
  return (
    <>
      {change.earlier.map((e) => (
        <p key={`${e.source.invoice_id}-${e.source.line_id}`} className="hint">
          {i18n.rich("earlier_line", {
            no: e.source.invoice_no, date: i18n.day(e.source.date),
            price: <Num source={invoiceSource(e.source, i18n)}>{i18n.money(e.pack_price)}</Num>,
            pack: packText(e, i18n),
          })}
        </p>
      ))}
    </>
  );
}
