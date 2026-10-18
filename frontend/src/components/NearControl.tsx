import { useState } from "react";
import { apiFetch } from "../api";
import { DEFAULT_NEAR, DEFAULT_RADIUS, type Near, type NearChoice, RADII, deviceNear, makeNear } from "../lib/eventsNear";
import { IconPin } from "./icons";
import { Modal } from "./ui/Modal";

/** "Within 15 miles of Cherry Hill, NJ" on /local: how far out the list
 * looks, and from where. Until a visitor picks a place it says outright
 * that Cherry Hill is our assumption. The browser's location is only ever
 * requested by the "Use my current location" button - never on page load. */
export function NearControl({ choice, onChange }: { choice: NearChoice; onChange: (choice: NearChoice) => void }) {
  const { near, radius } = choice;
  const [open, setOpen] = useState(false);
  const assumed = near.kind === "default";
  return (
    <div className="nearRow">
      <label>
        <span>Within</span>
        <select
          aria-label="Distance"
          value={radius ?? "any"}
          onChange={(e) => onChange({ near, radius: e.target.value === "any" ? null : Number(e.target.value) })}
        >
          {RADII.map((r) => (
            <option key={r} value={r}>
              {r} miles
            </option>
          ))}
          <option value="any">any distance</option>
        </select>
      </label>
      <span>
        of <b>{near.label}</b>
        {assumed && " (assumed)"}
      </span>
      {assumed ? (
        // Same look as Localz's "What am I eligible for?": the thing to press first.
        <button type="button" className="btn nearSet" onClick={() => setOpen(true)}>
          <IconPin />
          Set my location
        </button>
      ) : (
        <button type="button" className="ghost" onClick={() => setOpen(true)}>
          Change location
        </button>
      )}
      {open && (
        <NearDialog
          near={near}
          onClose={() => setOpen(false)}
          onPick={(picked) => {
            // Someone who had switched the distance off and now says where
            // they are wants it to matter again.
            onChange({ near: picked, radius: radius ?? DEFAULT_RADIUS });
            setOpen(false);
          }}
        />
      )}
    </div>
  );
}

function NearDialog({ near, onClose, onPick }: { near: Near; onClose: () => void; onPick: (near: Near) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<"device" | "place" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const useDevice = async () => {
    setBusy("device");
    setError(null);
    try {
      onPick(await deviceNear());
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  };

  const findPlace = async () => {
    const q = text.trim();
    if (q.length < 2) return;
    setBusy("place");
    setError(null);
    try {
      // POST: an address belongs in the body, not in a logged URL.
      const r = await apiFetch("/local-events/place", { method: "POST", body: JSON.stringify({ q }) });
      const body = await r.json().catch(() => null);
      if (!r.ok) throw new Error(typeof body?.detail === "string" ? body.detail : "Couldn't look that up right now - please try again.");
      onPick(makeNear(body.label, body.latitude, body.longitude, "place"));
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  };

  return (
    <Modal open onClose={onClose} title="Events near where?" subtitle={`Now measuring from ${near.label}.`}>
      <form
        className="nearForm"
        onSubmit={(e) => {
          e.preventDefault();
          void findPlace();
        }}
      >
        <label className="field">
          <span className="lbl">Address, town or ZIP code</span>
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="08003 or 123 Main St, Haddonfield" autoComplete="postal-code" enterKeyHint="search" />
        </label>
        <button type="submit" className="btn btn-primary" disabled={busy !== null || text.trim().length < 2}>
          {busy === "place" ? "Looking…" : "Use this place"}
        </button>
      </form>
      <div className="nearOr">or</div>
      <button type="button" className="btn" style={{ width: "100%" }} onClick={useDevice} disabled={busy !== null}>
        {busy === "device" ? "Waiting for your location…" : "Use my current location"}
      </button>
      {error && (
        <p className="nearError" role="alert">
          {error}
        </p>
      )}
      <p className="note" style={{ marginTop: 12 }}>
        Your browser will ask before sharing your location. Either way it's used only to measure distance, rounded to about half a mile, and
        remembered in this browser - not in an account.
      </p>
      {near.kind !== "default" && (
        <button type="button" className="ghost" onClick={() => onPick(DEFAULT_NEAR)} disabled={busy !== null}>
          Go back to {DEFAULT_NEAR.label}
        </button>
      )}
    </Modal>
  );
}
