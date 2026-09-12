import type { ReactNode } from "react";

type Props = {
  label: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  className?: string;
  children: ReactNode;
};

/** Label + control + hint/error, laid out consistently. Wrap a native
 * input/select/textarea - the control itself stays native. */
export function Field({ label, hint, error, className = "", children }: Props) {
  return (
    <label className={`field ${error ? "invalid" : ""} ${className}`}>
      <span className="lbl">{label}</span>
      {children}
      {error ? <span className="err">{error}</span> : hint ? <span className="help">{hint}</span> : null}
    </label>
  );
}
