import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { SchoolContentItem } from "../types";

/** Marks text that schoolz translated by machine, with the school's own
 * wording one tap away. Renders nothing for anything the school wrote. */
export function TranslatedNote({ item }: { item: SchoolContentItem }) {
  const { t } = useTranslation();
  const [showOriginal, setShowOriginal] = useState(false);
  if (!item.translated) return null;
  const original = [item.title_original, item.description_original].filter(Boolean).join(" \u2014 ");
  return (
    <div className="note" style={{ marginTop: 4 }}>
      {t("Translated automatically.")}{" "}
      {original && (
        <button type="button" className="linklike" onClick={() => setShowOriginal((v) => !v)} aria-expanded={showOriginal}>
          {showOriginal ? t("Hide original") : t("See original")}
        </button>
      )}
      {showOriginal && original && <div lang="en" style={{ marginTop: 2 }}>{original}</div>}
    </div>
  );
}
