import type { ReactNode } from "react";
import { Modal } from "./Modal";

type Props = {
  open: boolean;
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  danger?: boolean;
  busy?: boolean;
  disabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
};

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger,
  busy,
  disabled,
  onConfirm,
  onCancel,
  children,
}: Props) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      footer={
        <>
          <button className="btn" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button className={`btn ${danger ? "solid-danger" : "btn-primary"}`} onClick={onConfirm} disabled={busy || disabled}>
            {busy ? "Working…" : confirmLabel}
          </button>
        </>
      }
    >
      {description && <p style={{ marginTop: 0, color: "var(--ink-2)" }}>{description}</p>}
      {children}
    </Modal>
  );
}
