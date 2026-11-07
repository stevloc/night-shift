// Morning Brief: what changed, which dish, the money effect, and the three action choices.
// "While You Slept" (verified / needs input / proposed) and the decision log live here too.

import { useState } from "react";
import { api, type Dish } from "../api";
import { useApp, useMediaQuery, type Route } from "../context";
import { dishName, dishStatus, packText, reasonText } from "../format";
import { invoiceSource, pctChangeSource, breakdownSources, targetSource } from "../sources";
import { Icon } from "../components/Icon";
import { Num } from "../components/Num";
import { HeldNotes, RecommendationCard } from "../components/Recommendation";
import { WhileYouSlept } from "../components/WhileYouSlept";

export function Brief(_: { route: Route }) {
  const { view, i18n, runNightShift, running, requestReset } = useApp();
  const { t, tp, rich, money, approx, name, pctPoints } = i18n;

  const decisionDishes = view.dishes.filter((d) => d.proposal || d.decision !== "open");
  const others = view.dishes.filter((d) => !decisionDishes.includes(d));
  const openDecisions = decisionDishes.filter((d) => d.decision === "open" && d.proposal).length;
  const saved = decisionDishes.filter((d) => d.decision === "approved").length;
  const needs = view.report.needs_input.length;
  const ran = view.has_run || view.invoices.length > 0;

  const summary = !ran ? [t("sum_not_run", { count: i18n.num(view.inbox.length) })] : [
    openDecisions > 0 && tp("sum_action", openDecisions),
    needs > 0 && tp("sum_review", needs),
    openDecisions === 0 && saved > 0 && t("sum_saved"),
    openDecisions === 0 && saved === 0 && needs === 0 && t("sum_clear"),
  ].filter(Boolean) as string[];

  // Landscape tablet (1024px+): dish list on the left, the selected dish on the right.
  const wide = useMediaQuery("(min-width: 1024px)");
  const ordered = [...decisionDishes].sort((a, b) => Math.abs(b.cost_change_monthly) - Math.abs(a.cost_change_monthly))
    .concat([...others].sort((a, b) => Number(b.held_by.length > 0) - Number(a.held_by.length > 0)));
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = ordered.find((d) => d.id === selectedId) ?? ordered[0];

  const heroEl = (
    <>
      <section className="hero" aria-labelledby="page-title">
        <p className="eyebrow">{view.restaurant} · {t("nav_brief")}</p>
        <h1 id="page-title" tabIndex={-1}>{t("greeting", { name: view.owner })}</h1>
        {summary.map((line) => <p key={line} className="summary">{line}</p>)}
        {!ran && (
          <div className="row">
            <button type="button" className="btn btn-primary btn-lg" onClick={runNightShift} disabled={running}>
              <Icon name="moon" />{t("run_button")}
            </button>
          </div>
        )}
        {running && <p className="row" role="status"><span className="spinner" />{t("running")}</p>}
        {ran && <p className="hint row"><Icon name="info" size={16} />{t("num_hint")}</p>}
      </section>
    </>
  );
  const changedEl = (
    <>
      {ran && view.changes.some((c) => c.alert) && (
        <section className="card stack" aria-labelledby="changed-title">
          <h2 id="changed-title">{t("what_changed")}</h2>
          <ul className="change-list">
            {view.changes.filter((c) => c.alert).map((c) => (
              <li key={c.ingredient} className={c.pct > 0 ? "alert" : undefined}>
                <Icon name={c.pct > 0 ? "alert" : "down"} size={20} />
                <div>
                  <p>
                    <strong>{rich("change_line", {
                      ingredient: name(view.ingredients[c.ingredient].name),
                      old: <Num source={invoiceSource(c.prev_source, i18n)}>{money(c.prev.pack_price)}</Num>,
                      new: <Num source={invoiceSource(c.source, i18n)}>{money(c.now.pack_price)}</Num>,
                      pack: packText(c.now, i18n),
                    })}</strong>{" "}
                    <span className={c.pct > 0 ? "text-bad" : "text-good"}>
                      ({rich(c.pct > 0 ? "change_up" : "change_down", {
                        pct: <Num source={pctChangeSource(c.prev, c.now, i18n)}>{i18n.pct(c.pct)}</Num> })})
                    </span>
                  </p>
                  <p className="hint">{t("used_in", { dishes: i18n.list(c.dishes.map((d) => dishName(view, d, i18n))) })}</p>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
  const decisionsEl = (
    <>
      {decisionDishes.length > 0 && (
        <section className="stack" aria-labelledby="decide-title">
          <h2 id="decide-title">{t("needs_decision")}</h2>
          {decisionDishes.map((d) => <RecommendationCard key={d.id} dish={d} />)}
        </section>
      )}
    </>
  );
  const wysEl = (
    <>
      {ran && <WhileYouSlept />}
    </>
  );
  const othersEl = (
    <>
      {ran && (
        <section className="card stack" aria-labelledby="others-title">
          <h2 id="others-title">{t("other_dishes")}</h2>
          <ul className="dish-list">
            {others.map((d) => {
              const s = dishStatus(d, i18n);
              const src = breakdownSources(d, d.now, view, i18n);
              return (
                <li key={d.id}>
                  <a href={`#/dishes/${d.id}`}>{name(d.name)}<Icon name="chevron" size={16} /></a>
                  <span className={`pill ${s.tone}`}><Icon name={s.icon} size={16} />{s.text}</span>
                  {/* Evidence for the status: amount left as a share of price vs. the target. */}
                  {!d.held_by.length && (
                    <span className="hint">
                      <Num source={src.margin_pct}>{pctPoints(d.now.margin_pct)}</Num>{" / "}
                      <Num source={targetSource(i18n)}>{pctPoints(view.settings.target_margin_pct)}</Num>
                    </span>
                  )}
                  {d.held_by.length > 0 && <div className="held-row"><HeldNotes dish={d} /></div>}
                </li>
              );
            })}
          </ul>
          <p className="hint row"><Icon name="info" size={16} />{t("excluded")}</p>
        </section>
      )}
    </>
  );
  const restEl = (
    <>
      <section className="card stack" aria-labelledby="log-title">
        <h2 id="log-title">{t("approval_log")}</h2>
        {view.decision_log.length === 0 ? <p className="hint">{t("log_empty")}</p> : (
          <div className="table-wrap" role="region" aria-labelledby="log-title" tabIndex={0}>
            <table>
              <caption>{t("approval_caption")}</caption>
              <thead>
                <tr>
                  <th scope="col">{t("col_time")}</th>
                  <th scope="col">{t("col_dish")}</th>
                  <th scope="col">{t("col_decision")}</th>
                  <th scope="col" className="num">{t("col_effect")}</th>
                  <th scope="col">{t("col_status")}</th>
                </tr>
              </thead>
              <tbody>
                {[...view.decision_log].reverse().map((a) => (
                  <tr key={a.id}>
                    <td><time dateTime={a.at}>{i18n.time(a.at)}</time></td>
                    <th scope="row">{dishName(view, a.dish, i18n)}</th>
                    <td>{a.kind === "price_scenario"
                      ? t("log_scenario", { from: money(a.from_price!), to: money(a.to_price!) })
                      : a.kind === "kept_price"
                        ? <>{t("log_kept", { price: money(a.from_price!), scenario: money(a.scenario_price!) })}
                          {a.note && <span className="hint"> · “{a.note}”</span>}</>
                        : t("log_dismissed", { reason: reasonText(a.reason!, a.note, i18n) })}</td>
                    <td className="num">{a.kind === "price_scenario" ? approx(a.monthly_change!) : "—"}</td>
                    <td>
                      {a.undone
                        ? <span className="pill neutral"><Icon name="undo" size={16} />{t("log_undone", { time: i18n.time(a.undone_at!) })}</span>
                        : a.kind === "price_scenario"
                          ? <span className="pill good"><Icon name="check" size={16} />{t("log_saved")}</span>
                          : a.kind === "kept_price"
                            ? <span className="pill neutral"><Icon name="check" size={16} />{t("log_kept_status")}</span>
                            : <span className="pill neutral"><Icon name="minus" size={16} />{t("log_dismissed_status")}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {view.invoices.length > 0 && (
        <div className="row">
          <button type="button" className="btn" aria-describedby="export-hint" onClick={() => api.downloadCsv()}>
            <Icon name="download" />{t("export_csv")}
          </button>
          <p id="export-hint" className="hint">{t("export_hint")}</p>
        </div>
      )}

      <div className="footer-actions row">
        {ran && (
          <button type="button" className="btn btn-ghost" onClick={runNightShift} disabled={running}>
            <Icon name="moon" />{t("run_button")}
          </button>
        )}
        <button type="button" className="btn btn-ghost" onClick={requestReset}><Icon name="refresh" />{t("reset")}</button>
      </div>
    </>
  );

  if (!wide || !ran) {
    return (
      <div className="stack-lg">
        {heroEl}
        {changedEl}
        {decisionsEl}
        {wysEl}
        {othersEl}
        {restEl}
      </div>
    );
  }

  return (
    <div className="stack-lg">
      {heroEl}
      <div className="brief-grid">
        <div className="brief-list stack-lg">
          <section className="card stack" aria-labelledby="dishes-title">
            <h2 id="dishes-title">{t("dishes_today")}</h2>
            <ul className="dish-rows">
              {ordered.map((d) => {
                const st = dishStatus(d, i18n);
                return (
                  <li key={d.id}>
                    <button type="button" className="dish-row" aria-pressed={d.id === selected?.id}
                      aria-controls="brief-detail" onClick={() => setSelectedId(d.id)}>
                      <span className="dish-row-name">{name(d.name)}</span>
                      <span className={`pill ${st.tone}`}><Icon name={st.icon} size={16} />{st.text}</span>
                      <span className="dish-row-figures">
                        {money(d.now.left)} · {pctPoints(d.now.margin_pct)}
                        {Math.abs(d.cost_change_monthly) > 0.5 && <> · {t("per_month_short", { monthly: approx(d.cost_change_monthly) })}</>}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            <p className="hint row"><Icon name="info" size={16} />{t("excluded")}</p>
          </section>
          {changedEl}
          {wysEl}
          {restEl}
        </div>
        <aside id="brief-detail" className="brief-detail" aria-label={t("selected_dish", { dish: selected ? name(selected.name) : "" })}>
          {selected && (selected.proposal || selected.decision !== "open"
            ? <RecommendationCard key={selected.id} dish={selected} />
            : <DishSummary key={selected.id} dish={selected} />)}
        </aside>
      </div>
    </div>
  );
}

/** Right-hand panel for a dish without a price decision: status, the numbers behind it, holds. */
function DishSummary({ dish }: { dish: Dish }) {
  const { view, i18n } = useApp();
  const { t, rich, money, pctPoints, name } = i18n;
  const st = dishStatus(dish, i18n);
  const src = breakdownSources(dish, dish.now, view, i18n);
  return (
    <article className="card rec" aria-labelledby={`sum-${dish.id}`}>
      <div className="card-head">
        <h3 id={`sum-${dish.id}`}>{name(dish.name)}</h3>
        <span className={`pill ${st.tone}`}><Icon name={st.icon} size={16} />{st.text}</span>
      </div>
      <section className="rec-block" aria-label={t("financial_effect")}>
        <p>
          <span className="label">{t("amount_left_short")}: </span>
          <strong>{rich("left_change", {
            before: <Num source={breakdownSources(dish, dish.before, view, i18n).left}>{money(dish.before.left)}</Num>,
            now: <Num source={src.left}>{money(dish.now.left)}</Num>,
            pct: <Num source={src.margin_pct}>{pctPoints(dish.now.margin_pct)}</Num>,
            target: <Num source={targetSource(i18n)}>{pctPoints(view.settings.target_margin_pct)}</Num>,
          })}</strong>
        </p>
      </section>
      {dish.held_by.length > 0 && <HeldNotes dish={dish} />}
      {dish.held_by.length > 0 && (
        <a className="btn btn-primary" href="#/invoices"><Icon name="eye" />{t("review_now")}</a>
      )}
      <div className="rec-foot">
        <a href={`#/dishes/${dish.id}`}>{t("see_calc")} <Icon name="chevron" size={16} /></a>
      </div>
    </article>
  );
}
