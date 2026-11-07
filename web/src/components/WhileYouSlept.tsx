// "While You Slept": three clearly separated groups.
//   Verified              - checks that passed, each with the numbers that were checked
//   Needs your input      - unresolved items
//   Proposed, not applied - anything awaiting (or saved for) the owner's DoorDash update
// Rule: never show a reassuring line without its evidence.

import type { ReactNode } from "react";
import type { ReportItem } from "../api";
import { useApp } from "../context";
import { activityText, dishName, ingredientName, statusWords } from "../format";
import type { Key } from "../i18n";
import { Icon, type IconName } from "./Icon";

export function WhileYouSlept() {
  const { view, i18n } = useApp();
  const { t, num } = i18n;
  const { verified, needs_input, proposed } = view.report;

  return (
    <section className="card stack wys" aria-labelledby="wys-title">
      <div>
        <h2 id="wys-title">{t("wys_title")}</h2>
        <p className="hint">{t("wys_intro")}</p>
      </div>

      <Group id="g-needs" tone="warn" icon="eye" title={t("g_needs")} count={needs_input.length} empty={t("g_needs_empty")}>
        {needs_input.map((item, i) => <NeedsItem key={i} item={item} />)}
      </Group>
      <Group id="g-proposed" tone="accent" icon="dollar" title={t("g_proposed")} count={proposed.length} empty={t("g_proposed_empty")}>
        {proposed.map((item, i) => <ProposedItem key={i} item={item} />)}
      </Group>
      <Group id="g-verified" tone="good" icon="checkCircle" title={t("g_verified")} count={verified.length} empty={t("g_verified_empty")}
        collapsed={t("g_verified_show", { count: num(verified.length) })}>
        {verified.map((item, i) => <VerifiedItem key={i} item={item} />)}
      </Group>

      <details className="activity">
        <summary><span className="chev"><Icon name="chevron" size={18} /></span>{t("full_log", { count: num(view.activity.length) })}</summary>
        <ol className="timeline">
          {view.activity.map((a) => (
            <li key={a.id}>
              <time dateTime={a.at}>{i18n.time(a.at)}</time>
              <span>{activityText(a, view, i18n)}</span>
            </li>
          ))}
        </ol>
      </details>
    </section>
  );
}

function Group({ id, tone, icon, title, count, empty, collapsed, children }: {
  id: string; tone: string; icon: IconName; title: string; count: number; empty: string;
  /** Summary text: the list starts closed (every check keeps its evidence, one tap away). */
  collapsed?: string; children: ReactNode;
}) {
  const { i18n } = useApp();
  const list = <ul className="wys-list">{children}</ul>;
  return (
    <section className={`wys-group ${tone}`} aria-labelledby={id}>
      <h3 id={id}><Icon name={icon} size={20} />{title} <span className="count">({i18n.num(count)})</span></h3>
      {count === 0 ? <p className="hint">{empty}</p>
        : collapsed ? <details className="more"><summary>{collapsed}</summary>{list}</details> : list}
    </section>
  );
}

function Item({ at, title, evidence, children }: { at?: string; title: ReactNode; evidence?: ReactNode; children?: ReactNode }) {
  const { i18n } = useApp();
  return (
    <li>
      {at && <time dateTime={at}>{i18n.time(at)}</time>}
      <div>
        <p className="wys-title">{title}</p>
        {evidence && <p className="wys-evidence">{evidence}</p>}
        {children}
      </div>
    </li>
  );
}

function VerifiedItem({ item }: { item: ReportItem }) {
  const { view, i18n } = useApp();
  const { t, money, num, pctPoints, list } = i18n;
  const ing = (k: string) => ingredientName(view, k, i18n);
  switch (item.kind) {
    case "invoice_new":
      return <Item at={item.at} title={t("v_invoice_new", { supplier: item.supplier, no: item.invoice_no })}
        evidence={t("v_invoice_new_ev", { total: money(item.total), file: item.file })} />;
    case "totals_match":
      return <Item at={item.at} title={t("v_totals_match", { no: item.invoice_no })}
        evidence={t("v_totals_ev", { lines: num(item.lines), sum: money(item.lines_sum), total: money(item.total) })} />;
    case "packs_parsed":
      return <Item at={item.at} title={t("v_packs_parsed", { no: item.invoice_no, parsed: num(item.parsed), of: num(item.of) })}
        evidence={list(item.items.map((x: any) => `${ing(x.ingredient)} ${num(x.pack_size)} ${i18n.unit(x.pack_unit, x.pack_size)}`))} />;
    case "duplicate_skipped":
      return <Item at={item.at} title={<strong>{t("v_duplicate", { no: item.invoice_no })}</strong>}
        evidence={t("v_duplicate_ev", { file: item.file, supplier: item.supplier, no: item.invoice_no,
          total: money(item.total), of_file: item.of_file, of_time: i18n.time(item.of_at) })} />;
    case "owner_confirmed": {
      const unit = (n: number) => i18n.unit(item.pack_unit, n);
      const common = { price: money(item.pack_price), size: num(item.pack_size), per_unit: i18n.unitMoney(item.per_unit), unit_one: unit(1) };
      return <Item at={item.at}
        title={<strong>{t("v_owner_confirmed", { ingredient: ing(item.ingredient).toLowerCase(), size: num(item.pack_size), unit: unit(item.pack_size) })}</strong>}
        evidence={item.packs ? t("v_owner_confirmed_packs", { ...common, packs: num(item.packs), per: num(item.per_pack), unit: unit(item.pack_size) })
          : t("v_owner_confirmed_size", common)} />;
    }
    case "recalculated":
      return <Item at={item.at} title={t("v_recalculated", { dishes: num(item.dishes) })}
        evidence={t("v_recalculated_ev", { invoice: num(item.invoice_prices), saved: num(item.saved_prices) })} />;
    case "correction_resolved":
      return <Item at={item.at} title={<strong>{t("v_correction_resolved", { no: item.invoice_no })}</strong>}
        evidence={t("v_correction_resolved_ev", { kept: item.kept_file, other: item.other_file })} />;
    case "correction_effect":
      return <Item at={item.at} title={<strong>{t("v_correction_effect", { dish: dishName(view, item.dish, i18n), cause: item.cause })}</strong>}
        evidence={t("v_correction_effect_ev", { food_from: money(item.food_from), food_to: money(item.food_to),
          left_from: money(item.left_from), left_to: money(item.left_to), status: statusWords(item.status_to, i18n) })} />;
    case "cost_up_ok":
      return <Item at={item.at} title={t("v_cost_up_ok", { dish: dishName(view, item.dish, i18n) })}
        evidence={t("v_cost_up_ok_ev", { margin: pctPoints(item.margin), target: pctPoints(item.target), change: money(item.cost_change, true) })}>
        <a href={`#/dishes/${item.dish}`}>{t("see_calc")} <Icon name="chevron" size={16} /></a>
      </Item>;
    default:
      return null;
  }
}

function NeedsItem({ item }: { item: ReportItem }) {
  const { view, i18n } = useApp();
  const { t, money, num, list } = i18n;
  if (item.kind === "possible_correction") {
    return (
      <Item at={item.at} title={<strong>{t("n_possible_correction", { no: item.invoice_no })}</strong>}
        evidence={t("n_possible_correction_ev", { file: item.file, of_file: item.of_file,
          total: item.total == null ? "—" : money(item.total), of_total: item.of_total == null ? "—" : money(item.of_total) })}>
        <a href="#/invoices">{t("pc_choose")} <Icon name="chevron" size={16} /></a>
      </Item>
    );
  }
  if (item.kind === "totals_mismatch") {
    return <Item at={item.at} title={t("n_totals_mismatch", { no: item.invoice_no })}
      evidence={t("v_totals_ev", { lines: num(item.lines), sum: money(item.lines_sum), total: item.total == null ? "—" : money(item.total) })} />;
  }
  return (
    <Item at={item.at} title={<strong>{t("n_line_review", { no: item.invoice_no, original: item.original })}</strong>}
      evidence={item.reasons.map((r: string) => t(`reason_${r}` as Key)).join(" ")}>
      {item.dishes.length > 0 && <p className="hint">{t("review_holds", { dishes: list(item.dishes.map((d: string) => dishName(view, d, i18n))) })}</p>}
      <a href="#/invoices">{t("review_now")} <Icon name="chevron" size={16} /></a>
    </Item>
  );
}

function ProposedItem({ item }: { item: ReportItem }) {
  const { view, i18n } = useApp();
  const { t, money, approx, num } = i18n;
  const dish = dishName(view, item.dish, i18n);
  return item.state === "approved" ? (
    <Item title={<strong>{t("p_scenario_saved", { dish, from: money(item.from_price), to: money(item.to_price) })}</strong>}
      evidence={t("p_scenario_saved_ev", { time: i18n.time(item.approved_at) })} />
  ) : (
    <Item title={<strong>{t(!item.edited ? "p_scenario_open" : item.reaches_target ? "p_scenario_own" : "p_scenario_own_below",
      { dish, from: money(item.from_price), to: money(item.to_price), pct: i18n.pctPoints(item.margin ?? 0) })}</strong>}
      evidence={t("p_scenario_open_ev", { per: money(item.per_order_change, true), monthly: approx(item.monthly_change), orders: num(item.orders) })} />
  );
}
