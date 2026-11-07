// Shared app state for the 3 views: the server's view, language helpers,
// the screen-reader announcer, and shared actions.

import { createContext, useContext } from "react";
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
  requestAnimationFrame(() => requestAnimationFrame(() => document.getElementById(id)?.focus()));
}
