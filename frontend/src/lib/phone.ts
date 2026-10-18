/** US phone numbers as people read them: "(856) 555-0101", with an
 * extension after a comma: "(856) 555-0101, 12". The extension never counts
 * toward the 10 digits (backend `portal.phone_digits` agrees). */

const EXT = /[,;]|ext\.?|x/i;

const digits = (s: string) => s.replace(/\D/g, "");

/** The number's own 10 digits (a leading 1 dropped), extension excluded. */
export function mainDigits(p: string | null | undefined): string {
  const main = digits((p ?? "").split(EXT)[0]);
  return main.length === 11 && main.startsWith("1") ? main.slice(1) : main;
}

/** Formats as typed: "(856", "(856) 555", "(856) 555-0101". Digits past the
 * tenth become the extension, so typing straight through works too. */
export function formatPhone(raw: string): string {
  const [head, ...rest] = raw.split(EXT);
  const explicitExt = rest.length > 0;
  let d = digits(head);
  if (d.startsWith("1") && (d.length > 10 || !explicitExt)) d = d.slice(1);
  let ext = digits(rest.join(""));
  if (d.length > 10) {
    ext = d.slice(10) + ext;
    d = d.slice(0, 10);
  }
  let out = "";
  if (d.length > 0) out = `(${d.slice(0, 3)}`;
  if (d.length > 3) out += `) ${d.slice(3, 6)}`;
  if (d.length > 6) out += `-${d.slice(6)}`;
  if (d.length === 10 && (ext || explicitExt)) out += `, ${ext}`;
  return out;
}

/** The next value for a phone box, given what was there and what the
 * browser now has. Deleting only punctuation (the ")" or "-") would be
 * undone by formatting, so a backspace there removes the digit before it. */
export function nextPhoneValue(previous: string, raw: string): string {
  const next = formatPhone(raw);
  if (raw.length >= previous.length || next !== previous) return next;
  if (previous.endsWith(", ")) return previous.slice(0, -2);
  const last = raw.search(/\d\D*$/);
  return last < 0 ? "" : formatPhone(raw.slice(0, last) + raw.slice(last + 1));
}
