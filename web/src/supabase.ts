// Supabase in the browser is used ONLY to sign in (anonymous demo or email magic link).
// It gets the public anon key from /api/config; all data goes through our API with the user's token.

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let client: SupabaseClient | null = null;

export function supabaseClient(url: string, anonKey: string) {
  if (!client) {
    client = createClient(url, anonKey, {
      // PKCE puts the magic-link code in ?code=..., so it never collides with the app's #/ routes.
      auth: { flowType: "pkce", persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
    });
  }
  return client;
}
