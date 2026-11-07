// App shell: header, 3-view navigation, display settings, settings panel, live region.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Session, SupabaseClient } from "@supabase/supabase-js";
import { api, configureAuth, type Lang, type View } from "./api";
import { supabaseClient } from "./supabase";
import { SignIn } from "./pages/SignIn";
import { LANG_NAMES, LOCALES, makeT, type Key } from "./i18n";
import { AppContext, focusLater, type Route } from "./context";
import { errorText } from "./format";
import { Icon, type IconName } from "./components/Icon";
import { ConfirmDialog } from "./components/Dialog";
import { SettingsDialog } from "./components/SettingsDialog";
import { Brief } from "./pages/Brief";
import { InvoiceReview } from "./pages/InvoiceReview";
import { DishDetail } from "./pages/DishDetail";

const NAV: { page: Route["page"]; label: Key; icon: IconName }[] = [
  { page: "brief", label: "nav_brief", icon: "sun" },
  { page: "invoices", label: "nav_invoices", icon: "receipt" },
  { page: "dishes", label: "nav_dishes", icon: "table" },
];

function routeFromHash(): Route {
  const [page, dish] = window.location.hash.replace(/^#\/?/, "").split("/");
  if (page === "invoices") return { page: "invoices" };
  if (page === "dishes") return { page: "dishes", dish: dish ? decodeURIComponent(dish) : undefined };
  return { page: "brief" };
}

// Per-viewer display preferences; the app works the same if storage is unavailable.
const stored = (key: string) => { try { return localStorage.getItem(key); } catch { return null; } };
const store = (key: string, value: string) => { try { localStorage.setItem(key, value); } catch { /* private mode */ } };

export function App() {
  const [lang, setLang] = useState<Lang>(() => (stored("ns-lang") === "es" ? "es" : "en"));
  const [theme, setTheme] = useState<"night" | "day">(() =>
    (stored("ns-theme") as "night" | "day") ||
    (window.matchMedia("(prefers-color-scheme: light)").matches ? "day" : "night"));
  const [largeText, setLargeText] = useState(() => stored("ns-large") === "1");
  const [route, setRoute] = useState<Route>(routeFromHash);
  const [view, setView] = useState<View | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [message, setMessage] = useState("");
  const [uploading, setUploading] = useState(false);
  const [running, setRunning] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const firstRoute = useRef(true);

  const i18n = useMemo(() => makeT(lang), [lang]);
  const { t } = i18n;

  useEffect(() => { document.documentElement.dataset.theme = theme; store("ns-theme", theme); }, [theme]);
  useEffect(() => { document.documentElement.classList.toggle("large-text", largeText); store("ns-large", largeText ? "1" : "0"); }, [largeText]);
  useEffect(() => { document.documentElement.lang = LOCALES[lang]; store("ns-lang", lang); }, [lang]);

  // Auth: "off" = local demo mode (no Supabase). Otherwise sign in first; every API call carries the token.
  const [auth, setAuth] = useState<"checking" | "off" | "signed-out" | "signed-in">("checking");
  const [supabase, setSupabase] = useState<SupabaseClient | null>(null);
  const [emailSignin, setEmailSignin] = useState(false);   // off unless EMAIL_SIGNIN=true on the server
  useEffect(() => {
    let unsubscribe = () => {};
    api.config().then(async (cfg) => {
      if (!cfg.auth || !cfg.supabaseUrl || !cfg.supabaseAnonKey) { setAuth("off"); return; }
      const sb = supabaseClient(cfg.supabaseUrl, cfg.supabaseAnonKey);
      setEmailSignin(!!cfg.emailSignin);
      configureAuth(async () => (await sb.auth.getSession()).data.session?.access_token ?? null,
        () => { setView(null); setAuth("signed-out"); });
      const apply = (session: Session | null) => setAuth(session ? "signed-in" : "signed-out");
      apply((await sb.auth.getSession()).data.session);
      unsubscribe = sb.auth.onAuthStateChange((_event, session) => apply(session)).data.subscription.unsubscribe;
      setSupabase(sb);
    }).catch(() => setLoadError(true));
    return () => unsubscribe();
  }, []);

  const load = useCallback(async () => {
    try {
      setView(await api.state());
      setLoadError(false);
    } catch {
      setLoadError(true);
    }
  }, []);
  useEffect(() => { if (auth === "off" || auth === "signed-in") load(); }, [load, auth]);

  async function signOut() {
    await supabase?.auth.signOut();
    setView(null);
  }

  // Hash routing; focus the new page's h1 so screen readers announce it.
  useEffect(() => {
    const onHash = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const routeKey = route.page === "dishes" ? `dishes/${route.dish ?? ""}` : route.page;
  useEffect(() => {
    const current = NAV.find((n) => n.page === route.page)!;
    document.title = `${t(current.label)} · Night Shift`;
    if (firstRoute.current) { firstRoute.current = false; return; }
    focusLater("page-title");
  }, [routeKey, t]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Live region: clear then set, so repeated messages are read again.
  const announce = useCallback((text: string) => {
    setMessage("");
    window.setTimeout(() => setMessage(text), 60);
  }, []);

  /** Shared upload: returns an error sentence, or null on success. */
  const uploadInvoice = useCallback(async (file: Blob, name: string) => {
    // Same limits as the server (5 MB, images or PDF), checked first so the owner gets an instant answer.
    if (file.type && !file.type.startsWith("image/") && file.type !== "application/pdf") return t("err_bad_file");
    if (file.size > 5 * 1024 * 1024) return t("err_too_large");
    setUploading(true);
    announce(t("reading"));
    try {
      const r = await api.upload(file, name);
      setView(r.view);
      if (r.duplicate_of) {
        const text = t("dup_uploaded", { no: r.duplicate_of });
        announce(text);
        return text;
      }
      if (r.possible_correction) {
        const text = t("pc_uploaded", { no: r.possible_correction });
        announce(text);
        return text;
      }
      const inv = r.view.invoices.find((i) => i.id === r.invoice_id);
      const verified = inv ? inv.lines.filter((l) => l.status === "verified").length : 0;
      announce(t("inv_added", { verified: i18n.num(verified), review: i18n.num(r.review ?? 0) }));
      return null;
    } catch (e) {
      const text = errorText(e, i18n);
      announce(text);
      return text;
    } finally {
      setUploading(false);
    }
  }, [announce, i18n, t]);

  const runNightShift = useCallback(async () => {
    setRunning(true);
    announce(t("running"));
    try {
      const r = await api.run();
      setView(r.view);
      const dups = r.results.filter((x) => x.duplicate_of).length;
      announce(t("run_done", { invoices: i18n.num(r.results.length - dups), dups: i18n.num(dups) }));
    } catch (e) {
      announce(errorText(e, i18n));
    } finally {
      setRunning(false);
    }
  }, [announce, i18n, t]);

  const doReset = async () => {
    setConfirmReset(false);
    try {
      setView((await api.reset()).view);
      announce(t("reset_done"));
      window.location.hash = "/brief";
    } catch (e) {
      announce(errorText(e, i18n));
    }
  };

  const Page = { brief: Brief, invoices: InvoiceReview, dishes: DishDetail }[route.page];

  return (
    <>
      <a className="skip-link" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>
        {t("skip")}
      </a>

      <header className="site-header">
        <div className="shell">
          <div className="header-row">
            <a className="brand" href="#/brief">
              <span className="brand-mark"><Icon name="moon" size={24} /></span>
              <span>
                <span className="brand-name">{t("brand")}</span>
                <span className="brand-sub">{view ? `${view.restaurant} · ` : ""}{t("tagline")}</span>
              </span>
            </a>
            <div className="display-controls" role="group" aria-label={t("display")}>
              <div className="lang-field">
                <label htmlFor="lang">{t("language")}</label>
                <select id="lang" value={lang} onChange={(e) => setLang(e.target.value as Lang)}>
                  {(Object.keys(LANG_NAMES) as Lang[]).map((code) => (
                    <option key={code} value={code} lang={LOCALES[code]}>{LANG_NAMES[code]}</option>
                  ))}
                </select>
              </div>
              <button type="button" className="btn" onClick={() => setTheme(theme === "night" ? "day" : "night")}>
                <Icon name={theme === "night" ? "sun" : "moon"} />{theme === "night" ? t("to_day") : t("to_night")}
              </button>
              <button type="button" className="btn" aria-pressed={largeText} onClick={() => setLargeText(!largeText)}>
                <Icon name="textSize" />{t("larger_text")}
              </button>
              <button type="button" className="btn" onClick={() => setSettingsOpen(true)} disabled={!view}>
                <Icon name="settings" />{t("settings")}
              </button>
              {auth === "signed-in" && (
                <button type="button" className="btn" onClick={signOut}><Icon name="x" />{t("sign_out")}</button>
              )}
            </div>
          </div>
          {auth !== "signed-out" && <nav className="main-nav" aria-label={t("nav_label")}>
            <ul>
              {NAV.map((n) => (
                <li key={n.page}>
                  <a href={`#/${n.page}`} aria-current={route.page === n.page ? "page" : undefined}>
                    <Icon name={n.icon} size={22} />
                    <span>{t(n.label)}</span>
                  </a>
                </li>
              ))}
            </ul>
          </nav>}
        </div>
      </header>

      <main id="main" tabIndex={-1}>
        <div className="shell">
          {auth === "signed-out" && supabase ? (
            <SignIn supabase={supabase} i18n={i18n} emailSignin={emailSignin} />
          ) : view ? (
            <AppContext.Provider value={{
              view, setView, lang, i18n, announce, uploadInvoice, uploading, runNightShift, running,
              requestReset: () => setConfirmReset(true),
            }}>
              <Page route={route} />
              {settingsOpen && <SettingsDialog onClose={() => setSettingsOpen(false)} />}
            </AppContext.Provider>
          ) : loadError ? (
            <div className="card empty" role="alert">
              <h1 id="page-title" tabIndex={-1}>{t("brand")}</h1>
              <p>{t("error_load")}</p>
              <button type="button" className="btn btn-primary" onClick={load}><Icon name="refresh" />{t("retry")}</button>
            </div>
          ) : (
            <div className="empty" role="status"><span className="spinner" />{t("loading")}</div>
          )}
        </div>
      </main>

      <div className="sr-only" aria-live="polite" aria-atomic="true">{message}</div>

      <ConfirmDialog
        open={confirmReset} title={t("reset_title")} body={t("reset_body")}
        yes={t("reset_yes")} no={t("cancel")} danger closeLabel={t("close")}
        onYes={doReset} onNo={() => setConfirmReset(false)}
      />
    </>
  );
}
