// Dish Detail: the full calculation, step by step, before vs. now vs. the price scenario.
// Recipe amounts are editable; the server recomputes everything as you type (saved only on "Save recipe").

import { useEffect, useState } from "react";
import { api, type Dish } from "../api";
import { useApp, type Route } from "../context";
import { dishStatus, errorText, fieldError, fieldErrors, ingredientName, packText } from "../format";
import { breakdownSources, costChangeSource, invoiceSource, monthlySource, ordersSource, perOrderSource, targetSource } from "../sources";
import { Icon } from "../components/Icon";
import { Num, type NumSource } from "../components/Num";

export function DishDetail({ route }: { route: Route }) {
  const { view, setView, i18n, announce } = useApp();
  const { t, money, num, name, pctPoints, unitMoney } = i18n;
  const wanted = route.page === "dishes" ? route.dish : undefined;
  const saved = view.dishes.find((d) => d.id === wanted)
    ?? view.dishes.find((d) => d.proposal && d.decision === "open") ?? view.dishes[0];

  // Recipe editing: amounts typed by the owner, and the server's live preview of the whole dish.
  const [editing, setEditing] = useState(false);
  const [amounts, setAmounts] = useState<Record<string, string>>({});
  const [previewDish, setPreviewDish] = useState<Dish | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  useEffect(() => { setEditing(false); setPreviewDish(null); setErrors({}); }, [saved.id]);
  useEffect(() => {
    if (!editing) return;
    const timer = window.setTimeout(async () => {
      try {
        setPreviewDish((await api.previewRecipe(saved.id, amounts)).dish);
        setErrors({});
      } catch (e) {
        setErrors(fieldErrors(e));
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [amounts, editing, saved.id]);

  function startEditing() {
    setAmounts(Object.fromEntries(saved.recipe_lines.map((l) => [l.ingredient, String(l.amount)])));
    setEditing(true);
  }
  async function saveRecipe() {
    try {
      setView((await api.saveRecipe(saved.id, amounts)).view);
      announce(t("recipe_saved"));
      setEditing(false);
      setPreviewDish(null);
    } catch (e) {
      const f = fieldErrors(e);
      setErrors(f);
      if (!Object.keys(f).length) announce(errorText(e, i18n));
    }
  }

  const dish = editing && previewDish ? previewDish : saved;
  const status = dishStatus(dish, i18n);
  const p = dish.proposal;
  const s = view.settings;
  const costChanged = Math.abs(dish.cost_change_per_order) > 0.004;

  const rows: { label: string; key: "price" | "commission" | "packaging" | "food_cost" | "left"; minus?: boolean; total?: boolean }[] = [
    { label: t("r_price"), key: "price" },
    { label: t("r_commission", { fee: pctPoints(s.commission_pct) }), key: "commission", minus: true },
    { label: t("r_packaging"), key: "packaging", minus: true },
    { label: t("r_ingredients"), key: "food_cost", minus: true },
    { label: t("r_left"), key: "left", total: true },
  ];
  const columns = [
    { label: t("c_before_change"), data: dish.before, src: breakdownSources(dish, dish.before, view, i18n) },
    { label: t("c_now_col"), data: dish.now, src: breakdownSources(dish, dish.now, view, i18n) },
    ...(p ? [{ label: t("c_proposed"), data: p.after, src: breakdownSources(dish, p.after, view, i18n, p) }] : []),
  ];

  return (
    <div className="stack-lg">
      <nav className="dish-picker" aria-label={t("dishes_label")}>
        <ul>
          {view.dishes.map((d) => (
            <li key={d.id}>
              <a href={`#/dishes/${d.id}`} aria-current={d.id === saved.id ? "page" : undefined}>{name(d.name)}</a>
            </li>
          ))}
        </ul>
      </nav>

      <div className="page-head">
        <h1 id="page-title" tabIndex={-1}>{name(dish.name)}</h1>
        <p><span className={`pill ${status.tone}`}><Icon name={status.icon} size={16} />{status.text}</span></p>
        {dish.held_by.length > 0 && (
          <p className="notice warn"><Icon name="pause" />
            {t("held_detail", { ingredients: i18n.list(dish.held_by.map((k) => ingredientName(view, k, i18n))) })}</p>
        )}
        <p className="hint row"><Icon name="info" size={16} />{t("excluded")} {t("num_hint")}</p>
      </div>

      <section className="card stack" aria-labelledby="step1">
        <div className="card-head">
          <h2 id="step1">{t("step1")}</h2>
          {editing ? (
            <div className="row">
              <button type="button" className="btn" onClick={() => { setEditing(false); setPreviewDish(null); setErrors({}); }}>
                {t("cancel")}
              </button>
              <button type="button" className="btn btn-primary" onClick={saveRecipe}><Icon name="check" />{t("recipe_save")}</button>
            </div>
          ) : (
            <button type="button" className="btn" onClick={startEditing}><Icon name="edit" />{t("edit_recipe")}</button>
          )}
        </div>
        {editing && <p className="notice warn" role="status"><Icon name="info" />{t("recipe_live")}</p>}
        <div className="table-wrap" role="region" aria-labelledby="step1" tabIndex={0}>
          <table>
            <caption>{t("step1_caption")}</caption>
            <thead>
              <tr>
                <th scope="col">{t("c_ingredient")}</th>
                <th scope="col">{t("c_pack")}</th>
                <th scope="col" className="num">{t("c_per_unit")}</th>
                <th scope="col" className="num">{t("c_yield")}</th>
                <th scope="col" className="num">{t("c_usable")}</th>
                <th scope="col" className="num">{t("c_amount")}</th>
                {costChanged && <th scope="col" className="num">{t("c_before")}</th>}
                <th scope="col" className="num">{t("c_now")}</th>
              </tr>
            </thead>
            <tbody>
              {dish.recipe_lines.map((l) => {
                const changed = Math.abs(l.cost - l.cost_before) > 0.004;
                const ingName = ingredientName(view, l.ingredient, i18n);
                const inputId = `amount-${l.ingredient}`;
                const recipeSrc: NumSource = { kind: "recipe", detail: t("sd_recipe", {
                  dish: name(dish.name), amount: `${num(l.amount)} ${i18n.unit(l.unit, l.amount)}` }) };
                return (
                  <tr key={l.ingredient}>
                    <th scope="row">{ingName}</th>
                    <td><Num source={invoiceSource(l.source, i18n)}>{money(l.pack_price)}</Num> / {packText(l, i18n)}</td>
                    <td className="num"><Num source={{ kind: "calc", detail: t("sd_per_unit", { price: money(l.pack_price), size: num(l.pack_size) }) }}>
                      {unitMoney(l.cost_per_unit)}</Num> / {i18n.unit(l.pack_unit)}</td>
                    <td className="num"><Num source={{ kind: "setting", detail: t("sd_yield", { ingredient: ingName }) }}>{pctPoints(l.yield_pct)}</Num></td>
                    <td className="num"><Num source={{ kind: "calc", detail: t("sd_usable", { per_unit: unitMoney(l.cost_per_unit), yield: pctPoints(l.yield_pct) }) }}>
                      {unitMoney(l.usable_cost_per_unit)}</Num> / {i18n.unit(l.pack_unit)}</td>
                    <td className="num">
                      {editing ? (
                        <span className="amount-edit">
                          <label htmlFor={inputId} className="sr-only">{t("amount_label", { ingredient: ingName, unit: i18n.unit(l.unit, 2) })}</label>
                          <input id={inputId} type="text" inputMode="decimal" value={amounts[l.ingredient] ?? ""}
                            onChange={(e) => setAmounts({ ...amounts, [l.ingredient]: e.target.value.replace(",", ".") })}
                            aria-invalid={!!errors[l.ingredient]} aria-describedby={errors[l.ingredient] ? `${inputId}-err` : undefined} />
                          {i18n.unit(l.unit, 2)}
                          {errors[l.ingredient] && <span id={`${inputId}-err`} className="field-error">{fieldError(errors[l.ingredient], i18n)}</span>}
                        </span>
                      ) : (
                        <Num source={recipeSrc}>{num(l.amount)} {i18n.unit(l.unit, l.amount)}</Num>
                      )}
                    </td>
                    {costChanged && <td className="num">{money(l.cost_before)}</td>}
                    <td className={`num ${changed ? "text-bad" : ""}`}>
                      {changed && <Icon name="up" size={14} />}
                      <Num source={{ kind: "calc", detail: t("sd_serving", {
                        amount: `${num(l.amount)} ${i18n.unit(l.unit, l.amount)}`, usable: `${unitMoney(l.usable_cost_per_unit)} / ${i18n.unit(l.pack_unit)}` }) }}>
                        {money(l.cost)}</Num>
                    </td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row" colSpan={6}>{t("total_food")}</th>
                {costChanged && <td className="num">{money(dish.before.food_cost)}</td>}
                <td className="num"><strong><Num source={columns[1].src.food_cost}>{money(dish.now.food_cost)}</Num></strong></td>
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      <section className="card stack" aria-labelledby="step2">
        <h2 id="step2">{t("step2")}</h2>
        <div className="table-wrap" role="region" aria-labelledby="step2" tabIndex={0}>
          <table className="calc">
            <caption>{t("step2_caption")} {t("amount_left")}.</caption>
            <thead>
              <tr>
                <th scope="col">{t("c_step")}</th>
                {columns.map((c) => <th key={c.label} scope="col" className="num">{c.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} className={r.total ? "total" : undefined}>
                  <th scope="row">{r.minus ? "− " : r.total ? "= " : ""}{r.label}</th>
                  {columns.map((c) => (
                    <td key={c.label} className={`num ${r.total && c.data.left < 0 ? "text-bad" : ""}`}>
                      <Num source={c.src[r.key]}>{money(c.data[r.key])}</Num>
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <th scope="row">{t("r_pct")}</th>
                {columns.map((c) => {
                  const below = c.data.margin_pct < s.target_margin_pct;
                  return (
                    <td key={c.label} className={`num ${below ? "text-warn" : "text-good"}`}>
                      <Icon name={below ? "trendDown" : "checkCircle"} size={14} />
                      <Num source={c.src.margin_pct}>{pctPoints(c.data.margin_pct)}</Num>
                    </td>
                  );
                })}
              </tr>
              <tr>
                <th scope="row">{t("r_target")}</th>
                {columns.map((c) => <td key={c.label} className="num"><Num source={targetSource(i18n)}>{pctPoints(s.target_margin_pct)}</Num></td>)}
              </tr>
            </tbody>
          </table>
        </div>
        <p className="hint">{i18n.rich("in_store", {
          price: <Num source={{ kind: "setting", detail: t("sd_instore_price", { dish: name(dish.name) }) }}>{money(dish.in_store.price)}</Num>,
          food: <Num source={columns[1].src.food_cost}>{money(dish.in_store.food_cost)}</Num>,
          left: money(dish.in_store.left),
        })}</p>
      </section>

      <section className="card stack" aria-labelledby="step3">
        <h2 id="step3">{t("step3")}</h2>
        <p>{costChanged ? i18n.rich("m_cost", {
          per: <Num source={costChangeSource(dish, i18n)}>{money(dish.cost_change_per_order, true)}</Num>,
          orders: <Num source={ordersSource(dish, i18n)}>{num(dish.monthly_orders)}</Num>,
          monthly: <Num source={monthlySource(dish.cost_change_per_order, dish, i18n)}>{money(dish.cost_change_monthly, true)}</Num>,
        }) : t("m_none")}</p>
        {p && <p><strong>{i18n.rich("m_proposal", {
          per: <Num source={perOrderSource(dish, p, view, i18n)}>{money(p.per_order_change, true)}</Num>,
          orders: <Num source={ordersSource(dish, i18n)}>{num(dish.monthly_orders)}</Num>,
          monthly: <Num source={monthlySource(p.per_order_change, dish, i18n)}>{money(p.monthly_change, true)}</Num>,
        })}</strong></p>}
        <p className="hint">{t("scenario_label", { orders: num(dish.monthly_orders) })}</p>
        {p && dish.decision === "open" && !editing && <a className="btn" href="#/brief"><Icon name="sun" />{t("approve_on_brief")}</a>}
      </section>
    </div>
  );
}
