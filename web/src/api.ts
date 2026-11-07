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
  /** Where the "before" (comparison) price came from. */
  source_before: Source;
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
  target_pct: number;
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
  /** Price scenarios: the owner's own price (vs. suggested) and whether it reached the target. */
  edited?: boolean;
  reaches_target?: boolean;
  margin_after?: number;
  target_pct?: number;
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
  /** What "before" means: prices before tonight's run, or the saved prices if Night Shift hasn't run. */
  comparison_basis: "before_run" | "saved_prices";
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

/** One per ingredient: the cost in use now vs. the explicit comparison. Earlier invoices are history only. */
export interface Change {
  ingredient: string;
  pct: number;
  alert: boolean;
  comparison: Pack;
  comparison_source: Source;
  comparison_basis: "before_run" | "saved_prices";
  current: Pack;
  current_source: Source;
  earlier: (Pack & { source: Source })[];
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

// ---------------------------------------------------------------- "Review my options"

export type OptionId = "keep_current" | "suggested" | "custom" | "limit";

export interface Sensitivity {
  available: boolean;
  reason?: "no_order_volume";
  orders?: number;
  baseline_total?: number;
  cases?: { decline: number; orders: number; scenario_total: number; change: number }[];
  threshold?: { decline: number | null; reason: null | "option_not_positive" | "baseline_not_positive" | "no_change" | "option_lower" };
}

export interface PriceOption {
  id: OptionId;
  price: number;
  after: Breakdown;
  reaches_target: boolean;
  loses_money: boolean;
  per_order_change: number;
  monthly_change: number | null;
  within_limit: boolean | null;
  sensitivity: Sensitivity | null;
}

export interface Evidence {
  id: string;
  provenance: "verified_invoice" | "owner_confirmed" | "previous_record" | "historical_invoice" | "needs_review"
    | "owner_entered" | "owner_reported" | "setting" | "forecast" | "calculated";
  text: string;
  link: string;
  ingredient?: string;
  invoice_no?: string;
}

/** Code-computed facts and options for one dish (the AI review reads the same snapshot). */
export interface Snapshot {
  dish: string;
  version: string;
  dish_status: DishStatus | "held";
  decision: Dish["decision"];
  current_price: number;
  now: Breakdown;
  settings: { commission_pct: number; packaging: number; target_margin_pct: number };
  monthly_orders: number;
  monthly_available: boolean;
  holds: {
    held_by: string[];
    review_lines: { ingredient: string; invoice_id: number; line_id: number; invoice_no: string; original: string; reasons: string[] }[];
    open_corrections: { id: number; invoice_no: string; file: string }[];
  };
  options: PriceOption[];
  conflicts: { kind: "limit_below_target_price"; limit: number; target_price: number; best_within_limit: OptionId;
    best_margin: number; best_reaches_target: boolean }[];
  allowed_actions: string[];
  owner: { note: string; max_price: number | null; max_increase: number | null; limit: number | null };
  evidence: Evidence[];
}

export interface DecisionReview {
  recommended_option_id: OptionId | null;
  summary: string;
  considerations: { category: "cost" | "customer" | "data_quality"; text: string; evidence_ids: string[]; basis: "records" | "owner_reported" }[];
  uncertainties: { text: string; evidence_ids: string[] }[];
  follow_up_question: string | null;
  next_action: string | null;
}

export interface ReviewResult {
  snapshot: Snapshot;
  status: "ok" | "held" | "no_options" | "stale" | "unavailable";
  reason?: "ai_not_configured" | "rate_limited" | "timeout" | "provider_error" | "invalid_output";
  retry_minutes?: number;
  review?: DecisionReview;
  provenance?: "live" | "cached";
  generated_at?: string;
  model?: string;
  snapshot_version?: string;
}

export interface Limits { max_price: string; max_increase: string }

// ---------------------------------------------------------------- "Investigate this alert"

export type InvestigationTool = "get_invoice_evidence" | "get_ingredient_cost_history" | "get_dish_context" | "calculate_price_scenario";

/** One tool execution that actually happened (never a reconstructed or fictional step). */
export interface InvestigationEvent {
  tool: InvestigationTool;
  status: "ok" | "held" | "missing" | "error";
  ingredient?: string | null;
  dish?: string | null;
  price?: number | null;
  ref?: string | null;
}

/** A price scenario exactly as Night Shift's calculator returned it. */
export interface CalculatedScenario {
  ref: string; dish_id: string; price: number; current_price: number; left_per_order: number; share_left_pct: number;
  reaches_target: boolean; target_pct: number; change_per_order_vs_today: number;
  monthly_change_if_orders_unchanged: number | null; order_decline_that_erases_gain_pct: number | null;
}

export interface InvestigationResult {
  snapshot: Snapshot;
  status: "ok" | "stale" | "unavailable";
  reason?: "ai_not_configured" | "rate_limited" | "tools_unsupported" | "timeout" | "deadline" | "provider_error"
    | "invalid_output" | "incomplete";
  retry_minutes?: number;
  finding?: {
    outcome: "ready_for_review" | "needs_confirmation" | "unavailable";
    summary: string; evidence_refs: string[]; scenario_ids: string[]; uncertainty: string[];
    question: string | null; next_step: string | null;
  } | null;
  events: InvestigationEvent[];
  refs?: Record<string, { kind: "invoice" | "history" | "saved_price" | "dish" | "sales" | "scenario";
    invoice_no?: string; ingredient?: string; date?: string; dish?: string }>;
  scenarios?: CalculatedScenario[];
  turns?: number; tool_executions?: number; elapsed_seconds?: number;
  /** How the invoice readings it used were produced: "saved" (replayed) and/or "ai" (read when they arrived). */
  readings?: ("saved" | "ai")[];
  model?: string;
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
  /** Deterministic comparison: no AI. */
  options: (dish: string, limits: Limits) => {
    const q = new URLSearchParams();
    if (limits.max_price.trim()) q.set("max_price", limits.max_price.trim());
    if (limits.max_increase.trim()) q.set("max_increase", limits.max_increase.trim());
    return request<{ snapshot: Snapshot }>(`/api/dishes/${dish}/options?${q}`);
  },
  /** One AI decision review. Read-only on the server. */
  review: (dish: string, body: Limits & { note: string; snapshot_version: string; lang: Lang }) =>
    request<ReviewResult>(`/api/dishes/${dish}/review`, send("POST", {
      ...body, max_price: body.max_price.trim() || null, max_increase: body.max_increase.trim() || null })),
  /** One bounded AI investigation (read-only on the server). */
  investigate: (dish: string, body: Limits & { note: string; snapshot_version?: string; lang: Lang }) =>
    request<InvestigationResult>(`/api/dishes/${dish}/investigate`, send("POST", {
      ...body, max_price: body.max_price.trim() || null, max_increase: body.max_increase.trim() || null })),
  restore: (dish: string) => request<WithView>(`/api/dishes/${dish}/restore`, send("POST")),
  saveSettings: (settings: Record<string, unknown>) => request<WithView>("/api/settings", send("PUT", settings)),
};
