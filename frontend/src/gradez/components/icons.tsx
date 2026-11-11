import type { ReactNode } from "react";
import type { GradezTab } from "../types";

// Line icons, drawn inline so a page that shows them needs no stylesheet of
// Gradez's (My family uses the tab icons on its rows).
function Icon({ size = 22, children }: { size?: number; children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

type Props = { size?: number };

export function IconHome({ size }: Props) {
  return (
    <Icon size={size}>
      <path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z" />
    </Icon>
  );
}

export function IconTodo({ size }: Props) {
  return (
    <Icon size={size}>
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M8.5 12.5l2.5 2.5 4.5-5.5" />
    </Icon>
  );
}

export function IconGrades({ size }: Props) {
  return (
    <Icon size={size}>
      <path d="M5 20V10M12 20V4M19 20v-7" />
    </Icon>
  );
}

export function IconSchedule({ size }: Props) {
  return (
    <Icon size={size}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </Icon>
  );
}

export function IconTeachers({ size }: Props) {
  return (
    <Icon size={size}>
      <path d="M5 5h14a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1h-7l-4 3.5V16H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z" />
    </Icon>
  );
}

export function TabIcon({ tab, size }: { tab: GradezTab; size?: number }) {
  if (tab === "grades") return <IconGrades size={size} />;
  if (tab === "schedule") return <IconSchedule size={size} />;
  if (tab === "teachers") return <IconTeachers size={size} />;
  return <IconTodo size={size} />;
}

export function IconChevronRight({ size = 18 }: Props) {
  return (
    <Icon size={size}>
      <path d="M9 6l6 6-6 6" />
    </Icon>
  );
}

export function IconChevronLeft({ size = 18 }: Props) {
  return (
    <Icon size={size}>
      <path d="M15 6l-6 6 6 6" />
    </Icon>
  );
}

export function IconChevronDown({ size = 16 }: Props) {
  return (
    <Icon size={size}>
      <path d="M6 9l6 6 6-6" />
    </Icon>
  );
}

export function IconCircleCheck({ size = 18 }: Props) {
  return (
    <Icon size={size}>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12.5l2.8 2.8L16 9.5" />
    </Icon>
  );
}

export function IconPencil({ size = 20 }: Props) {
  return (
    <Icon size={size}>
      <path d="M4 20h4l10-10-4-4L4 16v4z" />
      <path d="M13.5 6.5l4 4" />
    </Icon>
  );
}

export function IconCheck({ size = 20 }: Props) {
  return (
    <Icon size={size}>
      <path d="M5 12.5l4.5 4.5L19 7" />
    </Icon>
  );
}

export function IconClose({ size = 20 }: Props) {
  return (
    <Icon size={size}>
      <path d="M6 6l12 12M18 6L6 18" />
    </Icon>
  );
}

export function IconReread({ size }: Props) {
  return (
    <Icon size={size}>
      <path d="M20 12a8 8 0 1 1-2.6-5.9" />
      <path d="M20 4.5V9h-4.5" />
    </Icon>
  );
}

export function IconImport({ size }: Props) {
  return (
    <Icon size={size}>
      <path d="M12 15V4" />
      <path d="M7.5 8.5L12 4l4.5 4.5" />
      <path d="M5 15v4a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-4" />
    </Icon>
  );
}

export function IconFlag({ size }: Props) {
  return (
    <Icon size={size}>
      <path d="M5 21V4" />
      <path d="M5 5h11l-2 3.5 2 3.5H5" />
    </Icon>
  );
}

export function IconUser({ size }: Props) {
  return (
    <Icon size={size}>
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20c0-3.6 3.1-6 7-6s7 2.4 7 6" />
    </Icon>
  );
}

export function IconPeople({ size }: Props) {
  return (
    <Icon size={size}>
      <circle cx="9" cy="8.5" r="3" />
      <path d="M3 19.5c0-3 2.6-5 6-5s6 2 6 5" />
      <path d="M15.5 5.8a3 3 0 0 1 0 5.6M17.5 14.8c2 .6 3.5 2.2 3.5 4.7" />
    </Icon>
  );
}
