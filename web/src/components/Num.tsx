// A number that can explain itself. Tap, click, Enter/Space, or hover to see where it came from
// (invoice line, recipe, settings, forecast, or a calculation). Esc or tapping elsewhere closes it.
// WCAG 1.4.13: the popover is dismissible (Esc), hoverable (it sits inside the hover area) and persistent.

import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useApp } from "../context";
import type { Key } from "../i18n";

export type SourceKind = "invoice" | "previous" | "owner" | "recipe" | "setting" | "forecast" | "calc";
export interface NumSource { kind: SourceKind; detail: ReactNode }

const ICON: Record<SourceKind, string> = {
  invoice: "🧾", previous: "🧾", owner: "✍️", recipe: "🥣", setting: "⚙️", forecast: "📈", calc: "🧮",
};

export function Num({ children, source, className }: { children: ReactNode; source: NumSource; className?: string }) {
  const { i18n } = useApp();
  const [pinned, setPinned] = useState(false);
  const [hover, setHover] = useState(false);
  const open = pinned || hover;
  const id = useId();
  const wrapper = useRef<HTMLSpanElement>(null);
  const pop = useRef<HTMLSpanElement>(null);
  const leaveTimer = useRef<number | undefined>(undefined);  // short delay so the pointer can move onto the popover

  // The popover is position: fixed so scrolling tables can't clip it. Place it under the number
  // (or above, if there's no room), clamped to the screen with a 12px gutter; follow on scroll.
  useLayoutEffect(() => {
    const el = pop.current;
    const anchor = wrapper.current?.querySelector("button");
    if (!open || !el || !anchor) return;
    const place = () => {
      const gutter = 12;
      const btn = anchor.getBoundingClientRect();
      const screenW = document.documentElement.clientWidth;  // not innerWidth: it grows when content overflows on phones
      const screenH = document.documentElement.clientHeight;
      const { offsetWidth: w, offsetHeight: h } = el;
      const left = Math.min(Math.max(btn.left + btn.width / 2 - w / 2, gutter), screenW - gutter - w);
      const below = btn.bottom + 6;
      const top = below + h > screenH - gutter && btn.top - 6 - h > gutter ? btn.top - 6 - h : below;
      el.style.left = `${left}px`;
      el.style.top = `${top}px`;
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [open]);

  // Tapping anywhere else closes a pinned popover.
  useEffect(() => {
    if (!pinned) return;
    const onDown = (e: PointerEvent) => {
      if (!wrapper.current?.contains(e.target as Node)) setPinned(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [pinned]);

  return (
    <span ref={wrapper} className={`num-src ${className ?? ""}`}
      onMouseEnter={() => { window.clearTimeout(leaveTimer.current); setHover(true); }}
      onMouseLeave={() => { leaveTimer.current = window.setTimeout(() => setHover(false), 200); }}
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) { e.stopPropagation(); setPinned(false); setHover(false); }
      }}>
      <button type="button" className="num-btn" aria-expanded={open} aria-controls={id}
        onClick={() => setPinned(!pinned)}>
        {children}
      </button>
      <span ref={pop} id={id} role="note" className="num-pop" hidden={!open}>
        <strong><span aria-hidden="true">{ICON[source.kind]} </span>{i18n.t(`src_${source.kind}` as Key)}</strong>
        <span>{source.detail}</span>
      </span>
    </span>
  );
}
