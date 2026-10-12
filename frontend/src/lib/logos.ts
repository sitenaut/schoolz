import type { School } from "../types";

/** Class list for a school logo <img>, adding the backing disc its artwork
 * needs to stay visible.
 *
 * Districts publish logos made for their own site's header - a transparent
 * PNG in white ink for a dark header, or in dark ink for a white one - so on
 * the wrong theme here the image loads fine and there's just nothing to see.
 * Which disc a given file needs is worked out from its pixels by the backend
 * (services/logo_backing.py, during school_info.scan) and arrives as
 * `logo_backing`; null means not classified yet and renders bare. */
export function logoClass(base: string, school: Pick<School, "logo_backing"> | null | undefined): string {
  const backing = school?.logo_backing;
  return backing === "dark" || backing === "light" ? `${base} logo-${backing}` : base;
}
