// Typed client for the FastAPI backend. The server sends numbers and codes;
// the UI turns them into words (English / Spanish) and formats money per locale.

export type Lang = "en" | "es";
export type Names = Record<Lang, string>;
export type DishStatus = "loses_money" | "below_target" | "cost_up_ok" | "ok";

export interface Breakdown {
  price: number;
  commission: number;
  packaging: number;
  food_cost: number;
  left: number;
  margin_pct: number;
}

export interface Pack { pack_size: number; pack_unit: string; pack_price: number }

export interface Source {
  kind: "invoice" | "previous" | "owner";
  supplier: string;
  invoice_no: string;
  date: string;
  invoice_id?: number;
  line_id?: number;
  original?: string;
}

export interface RecipeLine extends Pack {
  ingredient: string;
  cost_per_unit: number;
  yield_pct: number;
  usable_cost_per_unit: number;
  amount: number;
  unit: string;
  cost: number;
  cost_before: number;
  pack_before: Pack;
  source: Source;
  recipe_amount: number;
}

export interface Proposal {
  price: number;
  suggested: number;
  edited: boolean;
  after: Breakdown;
  per_order_change: number;
  monthly_change: number;
  reaches_target: boolean;
  keep_per_dollar: number;
}

export interface Approval {
  id: number;
  at: string;
  dish: string;
  kind: "price_scenario" | "dismissed" | "kept_price";
  from_price?: number;
  to_price?: number;
  scenario_price?: number;
  left_before?: number;
  left_after?: number;
  per_order_change?: number;
  monthly_change?: number;
  monthly_orders?: number;
  commission_pct?: number;
  reason: string | null;
  note?: string;
  published: false;
  undone: boolean;
  undone_at?: string;
}

export interface Dish {
  id: string;
  name: Names;
  prices: { in_store: number; doordash: number };
  recipe_lines: RecipeLine[];
  recipe_edited: boolean;
  before: Breakdown;
  now: Breakdown;
  in_store: { price: number; food_cost: number; left: number };
  status: DishStatus;
  held_by: string[];
  /** Held ingredients: the last verified cost the dish keeps using until the owner confirms. */
  held_inputs: (Pack & { ingredient: string; source: Source })[];
  monthly_orders: number;
  /** The order history behind the monthly forecast. */
  order_basis: { orders: number; days: number; from: string; to: string; days_per_month: number; forecast: number; edited: boolean } | null;
  cost_change_per_order: number;
  cost_change_monthly: number;
  proposal: Proposal | null;
  decision: "open" | "approved" | "dismissed" | "kept";
  dismiss_reason: { code: string; note: string } | null;
  approval: Approval | null;
}

export interface Change {
  ingredient: string;
  pct: number;
  alert: boolean;
  prev: Pack;
  prev_source: Source;
  now: Pack;
  source: Source;
  invoice_id: number;
  line_id: number;
  original: string;
  has_image: boolean;
  dishes: string[];
}

/** One item in the "While You Slept" report. Fields depend on `kind`; every item has evidence. */
export interface ReportItem { kind: string; at?: string; [field: string]: any }

export interface Report { verified: ReportItem[]; needs_input: ReportItem[]; proposed: ReportItem[] }

export interface Duplicate {
  file: string; at: string; supplier: string; invoice_no: string; total: number; of_file: string; of_at: string;
}

export interface InvoiceLine {
  id: number;
  original: string;
  quantity: number | null;
  ingredient: string | null;
  pack_size: number | null;
  pack_unit: string | null;
  pack_price: number | null;
  status: "verified" | "needs_review";
  reasons: string[];
  corrected: boolean;
  normalized: { per_unit: number; unit: string; yield_pct: number; usable_per_unit: number } | null;
  change: number | null;
  has_image: boolean;
  line_total: number | null;
}

export interface Invoice {
  id: number;
  file: string;
  supplier: string;
  invoice_no: string;
  date: string;
  read_at: string;
  used_fallback: boolean;
  /** "ai" = read by the model when it arrived; "saved" = replayed from a stored reading. */
  extraction: "ai" | "saved";
  superseded_by: number | null;
  replaces: number | null;
  total: number | null;
  lines_sum: number;
  totals_match: boolean;
  lines: InvoiceLine[];
}

export interface DiffLine { original: string; quantity: number | null; pack_price: number | null }

/** Same supplier + invoice number as a counted invoice, but different contents. Not counted until the owner chooses. */
export interface PossibleCorrection {
  id: number; file: string; read_at: string; supplier: string; invoice_no: string; date: string;
  total: number | null; lines: number; extraction: "ai" | "saved";
  of_invoice: number; of_file: string; of_read_at: string; of_total: number | null; of_lines: number;
  only_new: DiffLine[]; only_counted: DiffLine[];
}

export interface Activity { id: number; at: string; kind: string; params: Record<string, any> }

export interface Settings {
  commission_pct: number;
  packaging: number;
  target_margin_pct: number;
  monthly_orders: Record<string, number>;
}

export interface View {
  owner: string;
  restaurant: string;
  has_run: boolean;
  inbox: string[];
  settings: Settings;
  commission_choices: number[];
  dismiss_reasons: string[];
  dishes: Dish[];
  changes: Change[];
  report: Report;
  invoices: Invoice[];
  duplicates: Duplicate[];
  possible_corrections: PossibleCorrection[];
  activity: Activity[];
  decision_log: Approval[];
  ingredients: Record<string, { name: Names; pack_unit: string; yield_pct: number; source: Source }>;
  units: string[];
}

/** A validation error from the server: codes the UI translates. */
export class ApiError extends Error {
  constructor(public detail: { error: string; fields?: Record<string, string>; min?: number; max?: number; retry_minutes?: number },
              public status: number) {
    super(detail.error);
  }
}

// Auth (Supabase mode): App.tsx registers how to get the current access token and what to do on 401.
let tokenGetter: (() => Promise<string | null>) | null = null;
let onUnauthorized: (() => void) | null = null;
export function configureAuth(getToken: () => Promise<string | null>, unauthorized: () => void) {
  tokenGetter = getToken;
  onUnauthorized = unauthorized;
}

/** fetch() with the user's access token attached (when signed in). */
export async function authFetch(path: string, init: RequestInit = {}) {
  const token = tokenGetter ? await tokenGetter() : null;
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(path, { ...init, headers });
  if (res.status === 401 && onUnauthorized) onUnauthorized();
  return res;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await authFetch(path, init);
  } catch {
    throw new ApiError({ error: "network" }, 0);
  }
  if (!res.ok) {
    let detail: ApiError["detail"] = { error: "generic" };
    try {
      const body = await res.json();
      if (body?.detail?.error) detail = body.detail;
    } catch { /* not JSON */ }
    throw new ApiError(detail, res.status);
  }
  return res.json();
}

const send = (method: string, body?: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: body === undefined ? undefined : JSON.stringify(body),
});

type WithView = { view: View };

export const api = {
  state: () => request<View>("/api/state"),
  reset: () => request<WithView>("/api/reset", send("POST")),
  run: () => request<WithView & { results: { file: string; duplicate_of?: string; review?: number }[] }>(
    "/api/run", send("POST")),
  upload: (file: Blob, name: string) => {
    const form = new FormData();
    form.append("file", file, name);
    return request<WithView & { invoice_id?: number; review?: number; duplicate_of?: string; possible_correction?: string }>(
      "/api/invoices", { method: "POST", body: form });
  },
  lineImageUrl: (invoiceId: number, lineId: number) => `/api/invoices/${invoiceId}/lines/${lineId}/image`,
  /** A short-lived link to the whole invoice (a signed Storage URL in production). */
  invoiceImageLink: (invoiceId: number) => request<{ url: string }>(`/api/invoices/${invoiceId}/image-url`),
  config: () => request<{ auth: boolean; supabaseUrl?: string; supabaseAnonKey?: string; emailSignin?: boolean }>("/api/config"),
  /** Download the bookkeeper CSV with the auth header (a plain link can't send it). */
  downloadCsv: async () => {
    const res = await authFetch("/api/export/bookkeeper.csv");
    if (!res.ok) throw new ApiError({ error: "generic" }, res.status);
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: "night-shift-invoices-2026-11-06.csv" });
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  },
  previewRecipe: (dish: string, amounts: Record<string, string>) =>
    request<{ dish: Dish }>(`/api/dishes/${dish}/recipe/preview`, send("POST", { amounts })),
  saveRecipe: (dish: string, amounts: Record<string, string>) =>
    request<WithView>(`/api/dishes/${dish}/recipe`, send("PUT", { amounts })),
  correctLine: (invoiceId: number, lineId: number, fields: Record<string, string>) =>
    request<WithView>(`/api/invoices/${invoiceId}/lines/${lineId}`, send("POST", fields)),
  preview: (dish: string, price: string) =>
    request<{ proposal: Proposal }>(`/api/dishes/${dish}/preview`, send("POST", { price })),
  setProposal: (dish: string, price: string) => request<WithView>(`/api/dishes/${dish}/proposal`, send("POST", { price })),
  approve: (dish: string) => request<WithView & { record: Approval }>(`/api/dishes/${dish}/approve`, send("POST")),
  undo: (dish: string) => request<WithView>(`/api/dishes/${dish}/undo`, send("POST")),
  dismiss: (dish: string, reason: string, note: string) =>
    request<WithView>(`/api/dishes/${dish}/dismiss`, send("POST", { reason, note })),
  keep: (dish: string, note: string) => request<WithView>(`/api/dishes/${dish}/keep`, send("POST", { note })),
  resolveCorrection: (id: number, choice: "keep_original" | "use_new") =>
    request<WithView>(`/api/corrections/${id}`, send("POST", { choice })),
  restore: (dish: string) => request<WithView>(`/api/dishes/${dish}/restore`, send("POST")),
  saveSettings: (settings: Record<string, unknown>) => request<WithView>("/api/settings", send("PUT", settings)),
};
