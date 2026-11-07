// Shared app state for the 3 views: the server's view, language helpers,
// the screen-reader announcer, and shared actions.

import { createContext, useContext, useEffect, useState } from "react";
import type { Lang, View } from "./api";
import type { I18n } from "./i18n";

export type Route = { page: "brief" } | { page: "invoices" } | { page: "dishes"; dish?: string };

export interface AppCtx {
  view: View;
  setView: (v: View) => void;
  lang: Lang;
  i18n: I18n;
  /** Speak a message to screen readers via the polite live region. */
  announce: (message: string) => void;
  /** Upload an invoice image (shared by the Brief and Invoice Review). */
  uploadInvoice: (file: Blob, name: string) => Promise<string | null>;
  uploading: boolean;
  /** Read every file in tonight's inbox (the overnight run). */
  runNightShift: () => Promise<void>;
  running: boolean;
  requestReset: () => void;
}

export const AppContext = createContext<AppCtx | null>(null);

export function useApp(): AppCtx {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp outside provider");
  return ctx;
}

/** Move focus to an element by id after React has rendered it. */
export function focusLater(id: string) {
  requestAnimationFrame(() => requestAnimationFrame(() => {
    const el = document.getElementById(id);
    // A target inside a closed <details> (e.g. a just-fixed invoice line) can't take focus: open it first.
    for (let d = el?.closest("details"); d; d = d.parentElement?.closest("details") ?? null) d.open = true;
    el?.focus();
  }));
}

/** True while a CSS media query matches (e.g. landscape tablet). Updates on rotate/resize. */
export function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => typeof window !== "undefined" && window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const update = () => setMatches(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, [query]);
  return matches;
}
