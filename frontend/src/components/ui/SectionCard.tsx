import type { ReactNode } from "react";

type Props = {
  title: string;
  description?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  danger?: boolean;
  children: ReactNode;
};

/** Katalyst-style settings section: card with a small uppercase label +
 * one-line description, optional icon tile, actions on the right, and an
 * optional footer row for Save/Cancel. */
export function SectionCard({ title, description, icon, actions, footer, danger, children }: Props) {
  return (
    <section className={`sc ${danger ? "danger" : ""}`}>
      <div className="sc-hd">
        <div className="sc-hd-l">
          {icon && <span className="sc-ico">{icon}</span>}
          <div style={{ minWidth: 0 }}>
            <div className="sc-t">{title}</div>
            {description && <div className="sc-d">{description}</div>}
          </div>
        </div>
        {actions && <div className="sc-hd-a">{actions}</div>}
      </div>
      {children}
      {footer && <div className="sc-ft">{footer}</div>}
    </section>
  );
}
