import type { TFunction } from "i18next";
import { BillsError } from "../../../lib/bills";

// One SVG per avatar key (backend/bills/catalog.py AVATARS). Fluent Emoji,
// MIT: avatars/LICENSE.txt. Shown as <img>, so an SVG can't run anything.
const FILES = import.meta.glob("./avatars/*.svg", { eager: true, query: "?url", import: "default" }) as Record<string, string>;
const URLS: Record<string, string> = Object.fromEntries(
  Object.entries(FILES).map(([path, url]) => [path.slice("./avatars/".length, -".svg".length), url]),
);
export const AVATAR_KEYS = Object.keys(URLS).sort();

export function Avatar({ name, size = 48 }: { name: string | null | undefined; size?: number }) {
  const src = name ? URLS[name] : undefined;
  if (!src) return <span className="bills-avatar bills-avatar-empty" style={{ width: size, height: size }} aria-hidden="true" />;
  return <img className="bills-avatar" src={src} width={size} height={size} alt="" />;
}

/** The fixed thank-you set, by key (the server's EMOJIS). */
export const EMOJIS: Record<string, string> = {
  heart: "❤️",
  pray: "\u{1f64f}",
  smile: "\u{1f60a}",
  party: "\u{1f389}",
  bulb: "\u{1f4a1}",
  sunflower: "\u{1f33b}",
};

/** A server error, in the visitor's language. */
export function errorText(t: TFunction, err: unknown): string {
  const code = err instanceof BillsError ? err.code : null;
  switch (code) {
    case "account_too_new":
      return t("New accounts can hold a bill after a day.");
    case "paused":
      return t("Holding bills is paused on your account.");
    case "holding_one":
      return t("Finish or let go of the bill you're holding first.");
    case "too_many_holds":
      return t("You've held a few bills today. Try again tomorrow.");
    case "not_available":
      return t("Someone else is already paying this one.");
    case "own_bill":
      return t("This is your own bill.");
    case "open_listing":
      return t("You already have a bill posted.");
    case "account_listed":
      return t("This account already has a bill posted.");
    case "account_recently_paid":
      return t("A neighbor paid a bill on this account recently. You can post again 60 days after that.");
    case "too_many_uploads":
      return t("That's a lot of uploads today. Try again tomorrow.");
    case "unsupported_file":
      return t("Upload a photo or a PDF of the bill.");
    case "file_too_big":
      return t("That file is too big. Try a smaller photo.");
    case "unreadable":
      return t("The bill couldn't be read just now. Try again, or try a clearer photo.");
    case "amount_not_allowed":
      return t("That amount isn't allowed.");
    case "account_number_invalid":
      return t("Check the account number.");
    case "zip_invalid":
      return t("Check the ZIP code.");
    case "amount_mismatch":
      return t("Enter the amount the bill asked for.");
    case "paid_on_invalid":
      return t("Check the date you paid.");
    case "hold_ended":
      return t("This hold has ended.");
    case "encryption_unavailable":
      return t("Neighborz isn't available right now.");
    default:
      return err instanceof BillsError && err.status === 409 ? t("That can't be done right now.") : t("Something went wrong. Try again.");
  }
}

/** Time left on a hold ("3 h 20 min left"). */
export function timeLeft(t: TFunction, iso: string): string {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return t("Ended");
  const hours = Math.floor(ms / 3_600_000);
  const minutes = Math.floor((ms % 3_600_000) / 60_000);
  return hours > 0 ? t("{{hours}} h {{minutes}} min left", { hours, minutes }) : t("{{minutes}} min left", { minutes });
}
