import { type FormEvent, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { IconPin } from "../../components/icons";
import { FilterSelect } from "../../components/ui/FilterSelect";
import { Modal } from "../../components/ui/Modal";
import { LOCALZ_COUNTIES } from "../../lib/localz";
import { type LocalzWhere, countiesForAreaCode, saveWhere, townForPoint, useLocalzWhere, whereForPoint, whereForZip } from "../../lib/localzWhere";

type GpsState = "idle" | "locating" | "denied" | "outside" | "unavailable";

/** "Set my location" - or, once set, "Bergen County" - and the modal behind
 * it: a ZIP, a phone area code, the phone's own location, or just a county.
 * All of it is worked out on the device (lib/localzWhere.ts). */
export function LocationButton() {
  const { t } = useTranslation();
  const where = useLocalzWhere();
  const [open, setOpen] = useState(false);
  const [zip, setZip] = useState("");
  const [zipError, setZipError] = useState(false);
  const [area, setArea] = useState("");
  const [areaCounties, setAreaCounties] = useState<string[] | null>(null);
  const [areaError, setAreaError] = useState(false);
  const [gps, setGps] = useState<GpsState>("idle");

  // A phone location saved before towns were named: name it once.
  useEffect(() => {
    if (where?.how !== "gps" || where.town || where.lat === undefined || where.lon === undefined) return;
    let stale = false;
    townForPoint(where.lat, where.lon).then((town) => {
      if (town && !stale) saveWhere({ ...where, town });
    });
    return () => {
      stale = true;
    };
  }, [where]);

  const reset = () => {
    setZip("");
    setZipError(false);
    setArea("");
    setAreaCounties(null);
    setAreaError(false);
    setGps("idle");
  };
  const close = () => {
    setOpen(false);
    reset();
  };
  const choose = (next: LocalzWhere | null) => {
    saveWhere(next);
    close();
  };

  const submitZip = async (e: FormEvent) => {
    e.preventDefault();
    const found = await whereForZip(zip);
    if (found) choose(found);
    else setZipError(true);
  };
  const submitArea = (e: FormEvent) => {
    e.preventDefault();
    const counties = countiesForAreaCode(area);
    setAreaCounties(counties);
    setAreaError(!counties);
  };
  const useMyLocation = () => {
    if (!("geolocation" in navigator)) {
      setGps("unavailable");
      return;
    }
    setGps("locating");
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        const found = await whereForPoint(pos.coords.latitude, pos.coords.longitude);
        if (found) choose(found);
        else setGps("outside");
      },
      (err) => setGps(err.code === err.PERMISSION_DENIED ? "denied" : "unavailable"),
      { enableHighAccuracy: false, timeout: 15000, maximumAge: 10 * 60 * 1000 },
    );
  };

  const countyLabel = (c: string) => t("{{county}} County", { county: c });
  const label = !where
    ? t("Set my location")
    : where.how === "zip" && where.zip
      ? t("Near {{zip}}", { zip: where.zip })
      : where.how === "gps"
        ? where.town
          ? t("Near {{town}}", { town: where.town })
          : t("Near my location")
        : countyLabel(where.county);

  return (
    <>
      <button className="btn localz-where" onClick={() => setOpen(true)} aria-label={where ? t("Location: {{place}}. Change", { place: label }) : label}>
        <IconPin />
        {label}
        {where?.how === "gps" && where.town && <span className="localz-where-how">{t("your location")}</span>}
      </button>
      <Modal open={open} onClose={close} title={t("Set my location")} subtitle={t("So Localz shows help that serves where you are.")}>
        <div className="localz-where-modal">
          <form className="localz-where-row" onSubmit={submitZip}>
            <label htmlFor="localz-zip">{t("ZIP code")}</label>
            <div className="localz-where-inline">
              <input
                id="localz-zip"
                inputMode="numeric"
                autoComplete="postal-code"
                maxLength={5}
                value={zip}
                onChange={(e) => {
                  setZip(e.target.value.replace(/\D/g, ""));
                  setZipError(false);
                }}
                placeholder="07075"
              />
              <button type="submit" className="btn btn-primary" disabled={zip.length !== 5}>
                {t("Use this ZIP")}
              </button>
            </div>
            {zipError && <p className="note">{t("That isn't a New Jersey ZIP code we know. Try a nearby one, or pick your county below.")}</p>}
          </form>

          <form className="localz-where-row" onSubmit={submitArea}>
            <label htmlFor="localz-area">{t("Phone area code")}</label>
            <div className="localz-where-inline">
              <input
                id="localz-area"
                inputMode="numeric"
                maxLength={3}
                value={area}
                onChange={(e) => {
                  setArea(e.target.value.replace(/\D/g, ""));
                  setAreaCounties(null);
                  setAreaError(false);
                }}
                placeholder="201"
              />
              <button type="submit" className="btn" disabled={area.length !== 3}>
                {t("Find counties")}
              </button>
            </div>
            {areaError && <p className="note">{t("That isn't a New Jersey area code. Try your ZIP code, or pick your county below.")}</p>}
            {areaCounties && (
              <div className="localz-where-choices" role="group" aria-label={t("Which county?")}>
                <span className="localz-muted">{t("Which county?")}</span>
                {areaCounties.map((c) => (
                  <button type="button" className="chip" key={c} onClick={() => choose({ county: c, how: "area", areaCode: area })}>
                    {countyLabel(c)}
                  </button>
                ))}
              </div>
            )}
          </form>

          <div className="localz-where-row">
            <button type="button" className="btn localz-where-gps" onClick={useMyLocation} disabled={gps === "locating"}>
              <IconPin />
              {gps === "locating" ? t("Finding you…") : t("Use my current location")}
            </button>
            {gps === "denied" && <p className="note">{t("Location is turned off for this site. You can use a ZIP code instead.")}</p>}
            {gps === "outside" && <p className="note">{t("You seem to be outside New Jersey. Pick a county instead.")}</p>}
            {gps === "unavailable" && <p className="note">{t("Couldn't get your location. Try a ZIP code instead.")}</p>}
          </div>

          <div className="localz-where-row">
            <label>{t("Or pick your county")}</label>
            <FilterSelect
              value={where?.county ?? ""}
              onChange={(c) => choose(c ? { county: c, how: "county" } : null)}
              ariaLabel={t("County")}
              placeholder={t("All of New Jersey")}
              clearLabel={t("All of New Jersey")}
              options={LOCALZ_COUNTIES.map((c) => ({ value: c, label: countyLabel(c) }))}
            />
          </div>

          <p className="localz-where-privacy">
            {t("This stays on your device. Your ZIP code and location are never sent to us: distances are measured on your phone, and we only see your county and a wide area around it.")}
          </p>
          {where && (
            <button type="button" className="btn ghost" onClick={() => choose(null)}>
              {t("Forget my location")}
            </button>
          )}
        </div>
      </Modal>
    </>
  );
}
