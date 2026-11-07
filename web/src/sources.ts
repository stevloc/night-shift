// Where each number came from, in words. Used by <Num> popovers on every screen.
// No math here: the formulas shown are filled in with numbers the backend already computed.

import type { Breakdown, Dish, Pack, Proposal, Source, View } from "./api";
import type { I18n } from "./i18n";
import type { NumSource } from "./components/Num";

export function invoiceSource(source: Source, i18n: I18n): NumSource {
  const { t } = i18n;
  if (source.kind === "previous") {
    return { kind: "previous", detail: t("sd_previous", { supplier: source.supplier, no: source.invoice_no, date: i18n.day(source.date) }) };
  }
  if (source.kind === "owner") {
    return { kind: "owner", detail: t("sd_owner", { supplier: source.supplier, no: source.invoice_no }) };
  }
  return { kind: "invoice", detail: t("sd_invoice", {
    supplier: source.supplier, no: source.invoice_no, date: i18n.day(source.date), original: source.original ?? "" }) };
}

/** Sources for every row of a DoorDash breakdown (price, fee, packaging, food, left, margin). */
export function breakdownSources(dish: Dish, b: Breakdown, view: View, i18n: I18n, proposal?: Proposal | null) {
  const { t, money, pctPoints, name } = i18n;
  const s = view.settings;
  const priceSource: NumSource = proposal
    ? { kind: "calc", detail: proposal.edited ? t("sd_scenario_price_edited")
      : t("sd_scenario_price", { target: pctPoints(s.target_margin_pct) }) }
    : { kind: "setting", detail: t("sd_menu_price", { dish: name(dish.name) }) };
  return {
    price: priceSource,
    commission: { kind: "calc", detail: t("sd_commission", { fee: pctPoints(s.commission_pct), price: money(b.price) }) } as NumSource,
    packaging: { kind: "setting", detail: t("sd_packaging") } as NumSource,
    food_cost: { kind: "calc", detail: t("sd_food") } as NumSource,
    left: { kind: "calc", detail: t("sd_left", {
      price: money(b.price), food: money(b.food_cost), packaging: money(b.packaging), commission: money(b.commission) }) } as NumSource,
    margin_pct: { kind: "calc", detail: t("sd_margin", { left: money(b.left), price: money(b.price) }) } as NumSource,
  };
}

export const targetSource = (i18n: I18n): NumSource => ({ kind: "setting", detail: i18n.t("sd_target") });

export function ordersSource(dish: Dish, i18n: I18n): NumSource {
  return { kind: "forecast", detail: i18n.t("sd_orders", { orders: i18n.num(dish.monthly_orders), dish: i18n.name(dish.name) }) };
}

export function monthlySource(perOrder: number, dish: Dish, i18n: I18n): NumSource {
  return { kind: "forecast", detail: i18n.t("sd_monthly", { per: i18n.money(perOrder, true), orders: i18n.num(dish.monthly_orders) }) };
}

export function costChangeSource(dish: Dish, i18n: I18n): NumSource {
  return { kind: "calc", detail: i18n.t("sd_cost_change", { now: i18n.money(dish.now.left), before: i18n.money(dish.before.left) }) };
}

export function perOrderSource(dish: Dish, p: Proposal, view: View, i18n: I18n): NumSource {
  return { kind: "calc", detail: i18n.t("sd_per_order", {
    after: i18n.money(p.after.left), now: i18n.money(dish.now.left), keep: i18n.money(p.keep_per_dollar),
    fee: i18n.pctPoints(view.settings.commission_pct) }) };
}

export function pctChangeSource(prev: Pack, now: Pack, i18n: I18n): NumSource {
  return { kind: "calc", detail: i18n.t("sd_pct_change", {
    unit: i18n.unit(now.pack_unit),
    old: i18n.unitMoney(prev.pack_price / prev.pack_size), new: i18n.unitMoney(now.pack_price / now.pack_size) }) };
}
