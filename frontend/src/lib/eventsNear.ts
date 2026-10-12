/** Where /local measures distance from, and how far out it looks.
 *
 * Kept in this browser only (localStorage) - there is no account setting and
 * nothing is stored server-side. Coordinates are rounded to two decimals
 * (about half a mile) before they are saved or sent: a radius is in miles,
 * so nothing finer is needed, and it keeps a visitor's exact position out
 * of request logs. */

export type Near = {
  label: string;
  lat: number;
  lng: number;
  /** default = our assumption; place = an address/ZIP they typed; device = the browser's location. */
  kind: "default" | "place" | "device";
};

export const DEFAULT_NEAR: Near = { label: "Cherry Hill, NJ", lat: 39.93, lng: -75.02, kind: "default" };
export const DEFAULT_RADIUS = 15;
export const RADII = [5, 10, 15, 25, 50];

/** `radius: null` is "any distance". */
export type NearChoice = { near: Near; radius: number | null };

const KEY = "schoolz_local_near_v1";
const coarse = (n: number) => Math.round(n * 100) / 100;

export function makeNear(label: string, lat: number, lng: number, kind: Near["kind"]): Near {
  return { label, lat: coarse(lat), lng: coarse(lng), kind };
}

export function loadNearChoice(): NearChoice {
  const fallback = { near: DEFAULT_NEAR, radius: DEFAULT_RADIUS };
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (!saved || typeof saved !== "object") return fallback;
    const n = saved.near;
    const near =
      n && typeof n.label === "string" && Number.isFinite(n.lat) && Number.isFinite(n.lng) && (n.kind === "place" || n.kind === "device")
        ? makeNear(n.label, n.lat, n.lng, n.kind)
        : DEFAULT_NEAR;
    const radius = saved.radius === null ? null : RADII.includes(saved.radius) ? (saved.radius as number) : DEFAULT_RADIUS;
    return { near, radius };
  } catch {
    return fallback;
  }
}

export function saveNearChoice(choice: NearChoice): void {
  try {
    // The default isn't saved as a place, so a visitor who never chose one
    // follows the default if it ever changes.
    localStorage.setItem(KEY, JSON.stringify({ near: choice.near.kind === "default" ? null : choice.near, radius: choice.radius }));
  } catch {
    // Private mode / storage blocked: the choice lasts for this visit.
  }
}

export function addNearParams(q: URLSearchParams, { near, radius }: NearChoice): void {
  q.set("near_lat", String(near.lat));
  q.set("near_lng", String(near.lng));
  if (radius !== null) q.set("radius_miles", String(radius));
}

/** The browser's position, asking permission if it hasn't been given.
 * Rejects with a message fit to show the visitor. */
export function deviceNear(): Promise<Near> {
  return new Promise((resolve, reject) => {
    if (!("geolocation" in navigator)) {
      reject(new Error("This browser can't share its location. Enter an address or ZIP code instead."));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve(makeNear("your current location", pos.coords.latitude, pos.coords.longitude, "device")),
      (err) =>
        reject(
          new Error(
            err.code === err.PERMISSION_DENIED
              ? "Location sharing is turned off for this site. Allow it in your browser's settings, or enter an address or ZIP code instead."
              : "Couldn't get your location. Try again, or enter an address or ZIP code instead.",
          ),
        ),
      // A radius in miles doesn't need GPS; a recent, coarse fix is quicker and easier on the battery.
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 10 * 60 * 1000 },
    );
  });
}
