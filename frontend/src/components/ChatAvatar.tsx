/** The chat assistant's mascot: a simplified backpack, echoing the
 * existing Backpack Capture mark but recolored to schoolz's own teal
 * (var(--primary)) so it reads as part of the site rather than a
 * bolted-on widget. Two dots on the front pocket read as a face. */
export function ChatAvatar({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 56 56" className={className} aria-hidden="true">
      <circle cx="28" cy="28" r="28" fill="var(--primary)" />
      <path d="M20 15 Q20 8 26 8 L26 20 L20 20 Z" fill="var(--primary-strong)" />
      <path d="M36 15 Q36 8 30 8 L30 20 L36 20 Z" fill="var(--primary-strong)" />
      <rect x="17" y="12" width="22" height="12" rx="6" fill="#f4fbfa" />
      <rect x="12" y="20" width="32" height="28" rx="8" fill="#ffffff" />
      <rect x="20" y="32" width="16" height="12" rx="4" fill="var(--primary)" />
      <circle cx="24" cy="38" r="1.6" fill="#ffffff" />
      <circle cx="32" cy="38" r="1.6" fill="#ffffff" />
    </svg>
  );
}
