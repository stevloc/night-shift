// <img> for images behind the API: fetched with the access token, shown from a blob URL.
// (A plain <img src> can't send an Authorization header.)

import { useEffect, useState } from "react";
import { authFetch } from "../api";

export function AuthImage({ src, alt, className }: { src: string; alt: string; className?: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    authFetch(src).then(async (res) => {
      if (!res.ok) throw new Error(String(res.status));
      objectUrl = URL.createObjectURL(await res.blob());
      if (!cancelled) setUrl(objectUrl);
    }).catch(() => !cancelled && setFailed(true));
    return () => { cancelled = true; if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [src]);
  if (failed) return null;
  return url ? <img className={className} src={url} alt={alt} /> : <div className={`${className ?? ""} img-loading`} role="img" aria-label={alt} />;
}

/** Link to the full invoice: asks the API for a short-lived signed URL, then opens it. */
export function InvoiceLink({ invoiceId, children, getLink }: {
  invoiceId: number; children: React.ReactNode; getLink: (id: number) => Promise<{ url: string }>;
}) {
  const [href, setHref] = useState<string | null>(null);
  useEffect(() => { getLink(invoiceId).then((r) => setHref(r.url)).catch(() => setHref(null)); }, [invoiceId, getLink]);
  if (!href) return null;
  return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
}
