import { useRef, useState } from "react";
import { apiFetch } from "../api";

type ImportResult = {
  districts_created: number;
  districts_updated: number;
  schools_created: number;
  schools_updated: number;
  smore_created: number;
  smore_updated: number;
  smore_skipped: string[];
  sacc_created: number;
  sacc_updated: number;
};

/** Admin-only: port centrally-managed setup (districts, schools, Smore
 * newsletter links, bell schedules, SACC info, and every scan they
 * imply) between environments - the UI for GET/POST /admin/config/*
 * (backend/routers/admin_config.py). Typical use: export from local,
 * paste the file into this same page pointed at the prod deployment, to
 * avoid re-entering everything by hand. See the README's "Porting
 * configuration to a new environment" section for the CLI equivalent
 * (scripts/migrate_config.py), which does the same thing without a
 * browser open on both environments at once. */
export function AdminConfigPage() {
  const [exportSummary, setExportSummary] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const [importText, setImportText] = useState("");
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const doExport = async () => {
    setExporting(true);
    setExportError(null);
    setExportSummary(null);
    try {
      const res = await apiFetch("/admin/config/export");
      if (!res.ok) throw new Error(await res.text());
      const body = await res.json();
      const json = JSON.stringify(body, null, 2);
      const blob = new Blob([json], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const stamp = body.exported_at?.slice(0, 10) ?? "export";
      a.href = url;
      a.download = `schoolz-config-${stamp}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setExportSummary(`Downloaded: ${body.districts.length} district(s), ${body.schools.length} school(s), ${body.smore_newsletters.length} newsletter(s).`);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : "Export failed.");
    } finally {
      setExporting(false);
    }
  };

  const onFilePicked = async (file: File | null) => {
    if (!file) return;
    setImportText(await file.text());
  };

  const doImport = async () => {
    setImporting(true);
    setImportError(null);
    setImportResult(null);
    let parsed: unknown;
    try {
      parsed = JSON.parse(importText);
    } catch {
      setImportError("That doesn't look like valid JSON - paste the exact file an export produced.");
      setImporting(false);
      return;
    }
    try {
      const res = await apiFetch("/admin/config/import", { method: "POST", body: JSON.stringify(parsed) });
      const body = await res.json();
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body));
      setImportResult(body);
    } catch (e) {
      setImportError(e instanceof Error ? e.message : "Import failed.");
    } finally {
      setImporting(false);
    }
  };

  return (
    <>
      <div className="h-row" style={{ marginTop: 0 }}>
        <h2>Import / export configuration</h2>
      </div>
      <p className="note">
        Ports centrally-managed setup - tracked districts and schools, Smore newsletter links, bell schedules, SACC info - to or from another schoolz
        deployment (e.g. local → prod), without re-entering everything by hand. Never includes accounts, linked children, or Gmail connections. Safe to
        re-run: matched by district name / school slug / newsletter URL, so importing the same file twice only updates what changed.
      </p>

      <div className="h-row">
        <h2>Export from this environment</h2>
      </div>
      <div className="card">
        <p className="note" style={{ marginTop: 0 }}>
          Downloads a JSON file with everything below - open it on the machine (or in the admin session) for the environment you want to import into,
          and paste it into the box underneath.
        </p>
        <button className="btn btn-primary" onClick={doExport} disabled={exporting}>
          {exporting ? "Exporting…" : "Export & download"}
        </button>
        {exportSummary && <p className="note" style={{ color: "var(--ok)" }}>{exportSummary}</p>}
        {exportError && <p className="note" style={{ color: "var(--bad)" }}>{exportError}</p>}
      </div>

      <div className="h-row">
        <h2>Import into this environment</h2>
      </div>
      <div className="card">
        <label>
          Exported JSON file
          <input ref={fileInput} type="file" accept="application/json" onChange={(e) => onFilePicked(e.target.files?.[0] ?? null)} />
        </label>
        <label>
          Or paste it directly
          <textarea
            value={importText}
            onChange={(e) => setImportText(e.target.value)}
            rows={8}
            placeholder="Paste the exported JSON here, or choose a file above."
            style={{ width: "100%", fontFamily: "monospace", fontSize: 12.5, marginTop: 4 }}
          />
        </label>
        <button className="btn btn-primary" onClick={doImport} disabled={importing || !importText.trim()} style={{ marginTop: 8 }}>
          {importing ? "Importing…" : "Import"}
        </button>
        {importError && <p className="note" style={{ color: "var(--bad)" }}>{importError}</p>}
        {importResult && (
          <div className="list" style={{ marginTop: 12 }}>
            <div className="row" style={{ gridTemplateColumns: "1fr" }}>
              <div className="what">
                <div className="ttl">Districts</div>
                <div className="desc">{importResult.districts_created} created · {importResult.districts_updated} updated</div>
              </div>
            </div>
            <div className="row" style={{ gridTemplateColumns: "1fr" }}>
              <div className="what">
                <div className="ttl">Schools</div>
                <div className="desc">{importResult.schools_created} created · {importResult.schools_updated} updated</div>
              </div>
            </div>
            <div className="row" style={{ gridTemplateColumns: "1fr" }}>
              <div className="what">
                <div className="ttl">Smore newsletters</div>
                <div className="desc">
                  {importResult.smore_created} created · {importResult.smore_updated} updated
                  {importResult.smore_skipped.length > 0 && ` · ${importResult.smore_skipped.length} skipped (no matching school here)`}
                </div>
                {importResult.smore_skipped.length > 0 && (
                  <div className="desc" style={{ marginTop: 4 }}>
                    Skipped: {importResult.smore_skipped.join(", ")}
                  </div>
                )}
              </div>
            </div>
            <div className="row" style={{ gridTemplateColumns: "1fr" }}>
              <div className="what">
                <div className="ttl">SACC programs</div>
                <div className="desc">{importResult.sacc_created} created · {importResult.sacc_updated} updated</div>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
