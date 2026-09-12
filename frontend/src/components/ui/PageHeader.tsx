import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { IconChevronLeft } from "../icons";

type Props = {
  upperTitle?: ReactNode;
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  back?: { to: string; label?: string };
};

export function PageHeader({ upperTitle, title, subtitle, actions, back }: Props) {
  return (
    <div>
      {back && (
        <Link to={back.to} className="ph-back">
          <IconChevronLeft /> {back.label ?? "Back"}
        </Link>
      )}
      <div className="ph">
        <div className="ph-titles">
          {upperTitle && <div className="ph-upper">{upperTitle}</div>}
          <h1>{title}</h1>
          {subtitle && <div className="ph-sub">{subtitle}</div>}
        </div>
        {actions && <div className="ph-actions">{actions}</div>}
      </div>
    </div>
  );
}
