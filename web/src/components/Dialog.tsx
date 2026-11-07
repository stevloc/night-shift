// Accessible modal built on native <dialog>: traps focus, Esc closes,
// focus moves in on open and returns to the opener on close.

import { useEffect, useId, useRef, type ReactNode } from "react";
import { Icon } from "./Icon";

interface Props {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  closeLabel: string;
  /** Hide the X button (e.g. while a step must finish). */
  hideClose?: boolean;
}

export function Dialog({ open, title, onClose, children, closeLabel, hideClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      opener.current = document.activeElement as HTMLElement;
      dialog.showModal();
      // Focus the field marked data-autofocus, else the first field, else the title.
      const field = dialog.querySelector<HTMLElement>("[data-autofocus]") ?? dialog.querySelector<HTMLElement>("input, select, textarea");
      (field ?? dialog.querySelector<HTMLElement>("h2"))?.focus();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  // Return focus to whatever opened the dialog.
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const restore = () => {
      const target = opener.current;
      if (target && document.contains(target)) target.focus();
    };
    dialog.addEventListener("close", restore);
    return () => {
      dialog.removeEventListener("close", restore);
      // Unmounted while open: leave modal state first (focus can't move outside a modal), then restore.
      if (dialog.open) { dialog.close(); restore(); }
    };
  }, []);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => { e.preventDefault(); onClose(); }}  // Esc
      onClick={(e) => { if (e.target === ref.current) onClose(); }}  // click on backdrop
    >
      {open && (
        <div className="dialog-body">
          <div className="dialog-head">
            <h2 id={titleId} tabIndex={-1}>{title}</h2>
            {!hideClose && (
              <button type="button" className="btn btn-ghost" onClick={onClose} aria-label={closeLabel}>
                <Icon name="x" />
              </button>
            )}
          </div>
          {children}
        </div>
      )}
    </dialog>
  );
}

/** Yes/No confirmation for anything that can't be undone. */
export function ConfirmDialog(props: {
  open: boolean; title: string; body: string; yes: string; no: string;
  onYes: () => void; onNo: () => void; closeLabel: string; danger?: boolean;
}) {
  return (
    <Dialog open={props.open} title={props.title} onClose={props.onNo} closeLabel={props.closeLabel}>
      <p>{props.body}</p>
      <div className="dialog-actions">
        <button type="button" className="btn" onClick={props.onNo}>{props.no}</button>
        <button type="button" className={props.danger ? "btn btn-danger" : "btn btn-primary"} onClick={props.onYes}>
          {props.yes}
        </button>
      </div>
    </Dialog>
  );
}
