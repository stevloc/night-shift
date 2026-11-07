// Sign-in: "Try the demo" (anonymous) or, when EMAIL_SIGNIN=true, a magic link by email.
// Every visitor gets their own demo restaurant. Email is off by default: Supabase's built-in mailer is
// rate-limited and only delivers to team members, so it needs custom SMTP first.

import { useId, useState } from "react";
import type { SupabaseClient } from "@supabase/supabase-js";
import type { I18n } from "../i18n";
import { Icon } from "../components/Icon";

export function SignIn({ supabase, i18n, emailSignin }: { supabase: SupabaseClient; i18n: I18n; emailSignin: boolean }) {
  const { t } = i18n;
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const emailId = useId(), errorId = useId();

  async function tryDemo() {
    setBusy(true);
    setError(null);
    const { error } = await supabase.auth.signInAnonymously();
    if (error) setError(t("signin_error"));
    setBusy(false);
  }

  async function sendLink(e: React.FormEvent) {
    e.preventDefault();
    if (!/^\S+@\S+\.\S+$/.test(email.trim())) {
      setError(t("signin_bad_email"));
      document.getElementById(emailId)?.focus();
      return;
    }
    setBusy(true);
    setError(null);
    const { error } = await supabase.auth.signInWithOtp({
      email: email.trim(), options: { emailRedirectTo: window.location.origin },
    });
    setBusy(false);
    if (error) setError(t("signin_error"));
    else setSent(true);
  }

  return (
    <div className="signin stack-lg">
      <section className="hero" aria-labelledby="page-title">
        <p className="eyebrow">{t("brand")}</p>
        <h1 id="page-title" tabIndex={-1}>{t("signin_title")}</h1>
        <p className="summary">{t("signin_intro")}</p>
        <div className="row">
          <button type="button" className="btn btn-primary btn-lg" onClick={tryDemo} disabled={busy}>
            <Icon name="play" />{t("try_demo")}
          </button>
        </div>
        <p className="hint row"><Icon name="info" size={16} />{t("demo_notice")}</p>
      </section>

      {emailSignin && <section className="card stack" aria-labelledby="email-title">
        <h2 id="email-title">{t("signin_email_title")}</h2>
        {sent ? (
          <p className="notice" role="status"><Icon name="checkCircle" />{t("link_sent", { email: email.trim() })}</p>
        ) : (
          <form className="stack" onSubmit={sendLink} noValidate>
            <div className="field">
              <label htmlFor={emailId}>{t("email_label")}</label>
              <input id={emailId} type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)}
                aria-invalid={!!error} aria-describedby={error ? errorId : undefined} style={{ maxWidth: "24rem" }} />
            </div>
            <div className="row">
              <button type="submit" className="btn" disabled={busy}><Icon name="external" />{t("send_link")}</button>
            </div>
          </form>
        )}
        {error && <p id={errorId} className="field-error" role="alert"><Icon name="alert" size={18} />{error}</p>}
      </section>}
      {!emailSignin && error && <p className="field-error" role="alert"><Icon name="alert" size={18} />{error}</p>}
    </div>
  );
}
