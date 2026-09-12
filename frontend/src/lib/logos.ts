/** Schools whose logo is a transparent PNG drawn in white/light ink.
 *
 * Those files are made for a dark header on the school's own site, so on
 * this app's light theme they render as an invisible square - the image
 * loads fine, there's just nothing to see. Confirmed for Beck
 * (`Beck_Logo-transparent.png`) and Malberg (`EMCC-logo-sml-transparent.png`).
 *
 * Keyed by slug rather than a database column: this is a property of the
 * image file the district happens to publish, not of the school, and a
 * migration for a cosmetic backing colour would be a lot of ceremony for
 * a two-entry list. If this grows past a handful, move it to a
 * `logo_needs_dark_backing` column on School and set it during
 * school_info.scan instead. */
const LIGHT_INK_LOGOS = new Set(["beck", "estelle-v-malberg"]);

export function logoNeedsDarkBacking(slug: string | null | undefined): boolean {
  return !!slug && LIGHT_INK_LOGOS.has(slug);
}

/** Class list for a school logo <img>, adding the dark backing when the
 * artwork would otherwise disappear on a light background. */
export function logoClass(base: string, slug: string | null | undefined): string {
  return logoNeedsDarkBacking(slug) ? `${base} logo-dark` : base;
}
