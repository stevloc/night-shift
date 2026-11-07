// Turns codes and numbers from the API into words in the current language.
// No math here: every amount was computed by the backend.

import { ApiError, type Activity, type Dish, type Pack, type View } from "./api";
import type { I18n, Key } from "./i18n";
import type { IconName } from "./components/Icon";

export type Tone = "bad" | "warn" | "good" | "neutral";

/** Status pill for a dish: icon + exact text, never color alone. */
export function dishStatus(dish: Dish, i18n: I18n): { tone: Tone; icon: IconName; text: string } {
  const { t } = i18n;
  if (dish.held_by.length) return { tone: "neutral", icon: "pause", text: t("st_held") };
  switch (dish.status) {
    case "loses_money": return { tone: "bad", icon: "alert", text: t("st_loses_money") };
    case "below_target": return { tone: "warn", icon: "trendDown", text: t("st_below_target") };
    case "cost_up_ok": return { tone: "good", icon: "info", text: t("st_cost_up_ok") };
    default: return { tone: "good", icon: "checkCircle", text: t("st_ok") };
  }
}

export function packText(pack: Pack, i18n: I18n) {
  return `${i18n.num(pack.pack_size)} ${i18n.unit(pack.pack_unit, pack.pack_size)}`;
}

export function dishName(view: View, id: string, i18n: I18n) {
  const dish = view.dishes.find((d) => d.id === id);
  return dish ? i18n.name(dish.name) : id;
}

export function ingredientName(view: View, key: string | null, i18n: I18n) {
  if (!key) return i18n.t("not_found");
  const info = view.ingredients[key];
  return info ? i18n.name(info.name) : key;
}

export function activityText(entry: Activity, view: View, i18n: I18n): string {
  const { t, money, pct, pctPoints, list, num } = i18n;
  const p = entry.params;
  const dish = (id: string) => dishName(view, id, i18n);
  const ing = (key: string) => ingredientName(view, key, i18n);
  switch (entry.kind) {
    case "shift_start": return t("ev_shift_start", { files: num(p.files) });
    case "brief_ready": return t("ev_brief_ready");
    case "invoice_read":
      return t("ev_invoice_read", { supplier: p.supplier || t("unknown_supplier"), no: p.invoice_no ?? "",
        lines: num(p.lines), review: num(p.review) });
    case "duplicate_skipped": return t("ev_duplicate_skipped", { no: p.invoice_no, file: p.file });
    case "price_change":
      return t(p.pct >= 0 ? "ev_price_change_up" : "ev_price_change_down", {
        ingredient: ing(p.ingredient), pct: pct(p.pct), old: money(p.old), new: money(p.new), no: p.invoice_no ?? "" });
    case "recalculated": return t("ev_recalculated", { dishes: num(p.dishes) });
    case "below_target": return t("ev_below_target", { dish: dish(p.dish), margin: pctPoints(p.margin) });
    case "loses_money": return t("ev_loses_money", { dish: dish(p.dish) });
    case "held": return t("ev_held", { dish: dish(p.dish), ingredients: list(p.ingredients.map(ing)) });
    case "hold_cleared": return t("ev_hold_cleared", { dish: dish(p.dish) });
    case "owner_confirmed":
      return t("ev_owner_confirmed", { ingredient: ing(p.ingredient).toLowerCase(), size: num(p.pack_size),
        unit: i18n.unit(p.pack_unit, p.pack_size) });
    case "recipe_changed":
      return t("ev_recipe_changed", { dish: dish(p.dish), ingredient: ing(p.ingredient).toLowerCase(),
        from: num(p.from), to: num(p.to), unit: i18n.unit(p.unit, p.to) });
    case "edited":   // the owner's own price scenario: say whether it reaches the target (older entries: no flag)
      return p.margin == null ? t("ev_edited", { dish: dish(p.dish), price: money(p.price) })
        : t(p.reaches_target ? "ev_edited_reaches" : "ev_edited_below", { dish: dish(p.dish), price: money(p.price), pct: pctPoints(p.margin) });
    case "approved":
      return p.reaches_target === false
        ? t("ev_approved_below", { dish: dish(p.dish), price: money(p.to_price), pct: pctPoints(p.margin) })
        : t(p.edited ? "ev_approved_own" : "ev_approved", { dish: dish(p.dish), price: money(p.to_price) });
    case "dismissed":
      return p.reason ? t("ev_dismissed_reason", { dish: dish(p.dish), reason: reasonText(p.reason, p.note, i18n) })
        : t("ev_dismissed", { dish: dish(p.dish) });
    case "kept_price":
      return t(p.note ? "ev_kept_price_note" : "ev_kept_price", { dish: dish(p.dish), price: money(p.price), note: p.note ?? "" });
    case "possible_correction": return t("ev_possible_correction", { no: p.invoice_no, file: p.file });
    case "correction_resolved": return t("ev_correction_resolved", { no: p.invoice_no, kept: p.kept_file });
    case "correction_effect":
      return t("ev_correction_effect", { dish: dish(p.dish), cause: p.cause, left_from: money(p.left_from), left_to: money(p.left_to) });
    case "undone": case "restored": return t(`ev_${entry.kind}` as Key, { dish: dish(p.dish) });
    case "settings_changed":
      return t("ev_settings_changed", { commission: pctPoints(p.commission_pct), target: pctPoints(p.target_margin_pct) });
    default: return entry.kind;
  }
}

/** A status code from the log ("held", "below_target", ...) as the same words the status pill uses. */
export function statusWords(code: string, i18n: I18n) {
  return i18n.t(code === "held" ? "st_held" : (`st_${code}` as Key));
}

/** "$38.00 / 500 sheets" */
export function costText(pack: Pack, i18n: I18n) {
  return `${i18n.money(pack.pack_price)} / ${packText(pack, i18n)}`;
}

export function reasonText(code: string, note: string | undefined, i18n: I18n) {
  return code === "other" && note ? note : i18n.t(`reason_${code}` as Key);
}

/** Server error -> sentence in the current language. */
export function errorText(error: unknown, i18n: I18n): string {
  if (error instanceof ApiError) {
    const { detail } = error;
    const text = i18n.t(`err_${detail.error}` as Key, {
      min: detail.min !== undefined ? i18n.money(detail.min) : "",
      max: detail.max !== undefined ? i18n.money(detail.max) : "",
      minutes: detail.retry_minutes !== undefined ? i18n.num(detail.retry_minutes) : "",
    });
    if (text !== `err_${detail.error}`) return text;
  }
  return i18n.t("err_generic");
}

/** Per-field validation codes ("required", "range:0:10", ...) -> sentence. */
export function fieldError(code: string | undefined, i18n: I18n): string | null {
  if (!code) return null;
  const [kind, min, max] = code.split(":");
  if (kind === "range") return i18n.t("field_range", { min: i18n.num(Number(min)), max: i18n.num(Number(max)) });
  const text = i18n.t(`field_${kind}` as Key);
  return text === `field_${kind}` ? i18n.t("err_generic") : text;
}

export function fieldErrors(error: unknown): Record<string, string> {
  return error instanceof ApiError && error.detail.fields ? error.detail.fields : {};
}
