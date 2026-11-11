import { useRef, useState } from "react";
import { PALETTE_HEXES, courseColorProps, defaultPaletteHex } from "../courses";
import { IconCheck, IconClose } from "./icons";
import { Sheet } from "./Sheet";

/** Rename or recolor one class. The change is this account's own: a child
 * and each guardian can call "GEOM A Per A 210-1" whatever they like without
 * the others seeing it (lib/coursePreferences.ts). */
export function ClassAppearance({
  courseKey,
  autoName,
  customName,
  customColor,
  onSetName,
  onSetColor,
  onClose,
}: {
  courseKey: string;
  autoName: string;
  customName?: string;
  customColor?: string;
  onSetName: (name: string | null) => void;
  onSetColor: (hex: string | null) => void;
  onClose: () => void;
}) {
  return (
    <Sheet onClose={onClose} label="Rename or recolor this class">
      <h2 className="gz-sheet-title">{customName?.trim() || autoName}</h2>
      <p className="gz-sheet-course">Only you see these changes.</p>
      <NamePicker autoName={autoName} customName={customName} onSetName={onSetName} />
      <ColorPicker courseKey={courseKey} customColor={customColor} onSetColor={onSetColor} />
      <button type="button" className="gz-primary" onClick={onClose}>
        Done
      </button>
    </Sheet>
  );
}

function NamePicker({
  autoName,
  customName,
  onSetName,
}: {
  autoName: string;
  customName?: string;
  onSetName: (name: string | null) => void;
}) {
  const [draft, setDraft] = useState(customName ?? "");
  const inputRef = useRef<HTMLInputElement>(null);

  // An empty field showing the auto name as its placeholder read as text
  // that needed deleting first, so the placeholder is an instruction and the
  // default is named underneath.
  const commit = () => {
    const trimmed = draft.trim();
    if (trimmed !== (customName ?? "")) onSetName(trimmed || null);
    inputRef.current?.blur();
  };

  const cancel = () => {
    setDraft(customName ?? "");
    inputRef.current?.blur();
  };

  return (
    <section className="gz-sheet-row gz-name-picker">
      <h3>Class name</h3>
      <div className="gz-name-row">
        <input
          ref={inputRef}
          className="gz-name-input"
          value={draft}
          placeholder="Enter a custom name"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") cancel();
          }}
          aria-label="Class display name"
        />
        {/* Always next to the field, rather than "tap away to save": on a
            phone the keyboard has the view zoomed in, and tapping either
            one blurs the input, which is what lets the browser un-zoom. */}
        <button type="button" className="gz-name-commit" aria-label="Save name" onClick={commit}>
          <IconCheck />
        </button>
        <button type="button" className="gz-name-cancel" aria-label="Cancel" onClick={cancel}>
          <IconClose />
        </button>
      </div>
      <p className="gz-name-hint">Leave blank to use the default: {autoName}</p>
    </section>
  );
}

function ColorPicker({
  courseKey,
  customColor,
  onSetColor,
}: {
  courseKey: string;
  customColor?: string;
  onSetColor: (hex: string | null) => void;
}) {
  const { className: defaultClassName } = courseColorProps(courseKey);
  // With no custom pick the class still has a color, the default one, and
  // the picker shows that as selected.
  const activeHex = customColor ?? defaultPaletteHex(courseKey);
  return (
    <section className="gz-sheet-row gz-color-picker">
      <h3>Class color</h3>
      <div className="gz-swatch-row">
        {PALETTE_HEXES.map((hex) => (
          <button
            key={hex}
            type="button"
            className={`gz-swatch${activeHex === hex ? " gz-swatch-selected" : ""}`}
            style={{ background: hex }}
            aria-label={`Use ${hex}`}
            aria-pressed={activeHex === hex}
            onClick={() => onSetColor(hex)}
          />
        ))}
        <label
          className={`gz-swatch gz-swatch-custom${customColor && !PALETTE_HEXES.includes(customColor) ? " gz-swatch-selected" : ""}`}
          aria-label="Pick a custom color"
        >
          <input type="color" value={customColor ?? "#888888"} onChange={(e) => onSetColor(e.target.value)} />
          <span aria-hidden="true">+</span>
        </label>
      </div>
      {customColor && (
        <button type="button" className="gz-ask-restart" onClick={() => onSetColor(null)}>
          Use the default color ({defaultClassName.replace("gz-tile-", "")})
        </button>
      )}
    </section>
  );
}
