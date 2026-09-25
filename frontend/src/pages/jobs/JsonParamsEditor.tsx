import { useEffect, useState } from "react";
import type { JobKind, JobParamSchema, TestFetchResult } from "../../types";

/* Ported from billz's ScheduledJobsAdminPage: the JSON params editor (tab
 * indents, CR stripping, bracket + JSON validation readout), the params help
 * (schema tree, Insert defaults, example JSON), and the test-fetch results
 * panel. Restyled onto schoolz's tokens; the behavior is billz's. */

/** A kind whose params aren't all flat strings needs the JSON editor - the
 * plain per-field form can't express lists or nested objects. */
export function needsJsonParams(spec: JobKind | null): boolean {
  const props = spec?.param_schema?.properties ?? {};
  return Object.values(props).some((p) => p.type === "array" || p.type === "object");
}

/** Kinds with a dry-run endpoint (routers/scheduled_jobs.py test-fetch). */
export const TEST_FETCH_KINDS = new Set(["local_events.refresh"]);

type BracketStatus = { balanced: boolean; message: string };

function analyzeBrackets(text: string): BracketStatus {
  const pairs: Record<string, string> = { ")": "(", "]": "[", "}": "{" };
  const opens = new Set(["(", "[", "{"]);
  const closes = new Set([")", "]", "}"]);
  const stack: { ch: string; line: number; col: number }[] = [];
  let line = 1;
  let col = 0;
  let inString = false;
  let escape = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    col++;
    if (ch === "\n") {
      line++;
      col = 0;
      continue;
    }
    if (escape) {
      escape = false;
      continue;
    }
    if (inString) {
      if (ch === "\\") {
        escape = true;
        continue;
      }
      if (ch === '"') inString = false;
      continue;
    }
    if (ch === '"') {
      inString = true;
      continue;
    }
    if (opens.has(ch)) {
      stack.push({ ch, line, col });
    } else if (closes.has(ch)) {
      const top = stack.pop();
      if (!top || top.ch !== pairs[ch]) return { balanced: false, message: `Unmatched '${ch}' at line ${line}, col ${col}` };
    }
  }
  if (stack.length) {
    const top = stack[stack.length - 1];
    return { balanced: false, message: `Unclosed '${top.ch}' from line ${top.line}, col ${top.col}` };
  }
  if (inString) return { balanced: false, message: "Unterminated string" };
  return { balanced: true, message: "Brackets balanced" };
}

export function JsonParamsEditor({ value, onChange }: { value: string; onChange: (text: string) => void }) {
  const status = (() => {
    if (!value.trim()) return null;
    const brackets = analyzeBrackets(value);
    let jsonErr = "";
    try {
      JSON.parse(value);
    } catch (e) {
      jsonErr = e instanceof Error ? e.message : String(e);
    }
    return { brackets, jsonErr, lines: value.split("\n").length };
  })();

  return (
    <div>
      <textarea
        className="json-params"
        value={value}
        spellCheck={false}
        // Strip \r so Windows-style \r\n line endings don't produce "bad
        // control character" JSON parse errors on paste.
        onChange={(e) => onChange(e.target.value.replace(/\r/g, ""))}
        onKeyDown={(e) => {
          // Tab inserts 2 spaces instead of moving focus.
          if (e.key !== "Tab") return;
          e.preventDefault();
          const ta = e.currentTarget;
          const start = ta.selectionStart;
          const end = ta.selectionEnd;
          onChange(value.slice(0, start) + "  " + value.slice(end));
          requestAnimationFrame(() => {
            ta.selectionStart = ta.selectionEnd = start + 2;
          });
        }}
      />
      {status && (
        <div className="json-status">
          <span>
            {status.lines} lines · {value.length} chars
          </span>
          <span className={status.brackets.balanced ? "ok" : "bad"}>
            {status.brackets.balanced ? "✓" : "✗"} {status.brackets.message}
          </span>
          <span className={status.jsonErr ? "bad" : "ok"}>{status.jsonErr ? `✗ ${status.jsonErr}` : "✓ Valid JSON"}</span>
          <button type="button" className="btn sm" onClick={() => navigator.clipboard?.writeText(value).catch(() => undefined)}>
            Copy
          </button>
        </div>
      )}
    </div>
  );
}

function SchemaFromSpec({ schema, depth = 0 }: { schema: JobParamSchema; depth?: number }) {
  const properties = schema.properties ?? {};
  const keys = Object.keys(properties);
  if (keys.length === 0) return <div className="schema-row muted" style={{ paddingLeft: depth * 14 }}>{schema.description ?? "(no fields)"}</div>;
  return (
    <div>
      {keys.map((key) => {
        const child = properties[key];
        const isRequired = (schema.required ?? []).includes(key);
        const typeLabel = child.type === "array" && child.items?.type ? `array<${child.items.type}>` : (child.type ?? "any");
        return (
          <div key={key} className="schema-row" style={{ paddingLeft: depth * 14 }}>
            <div>
              <code className="schema-key">{key}</code>
              {isRequired && (
                <span className="schema-req" title="required">
                  *
                </span>
              )}
              <span className="muted"> : </span>
              <span className="schema-type">{typeLabel}</span>
              {child.enum && child.enum.length > 0 && <span className="schema-extra">∈ {child.enum.map((v) => JSON.stringify(v)).join(" | ")}</span>}
              {child.default !== undefined && <span className="schema-extra">= {JSON.stringify(child.default)}</span>}
            </div>
            {child.description && <div className="schema-desc">{child.description}</div>}
            {child.type === "object" && child.properties && <SchemaFromSpec schema={child} depth={depth + 1} />}
            {child.type === "array" && child.items?.type === "object" && child.items.properties && (
              <div style={{ paddingLeft: (depth + 1) * 14 }}>
                <div className="schema-desc">items:</div>
                <SchemaFromSpec schema={child.items} depth={depth + 1} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function ParamsHelp({ kind, onInsertDefaults }: { kind: JobKind | null; onInsertDefaults: (params: Record<string, unknown>) => void }) {
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [kind?.kind]);
  if (!kind) return null;
  const defaults = kind.default_params ?? {};
  return (
    <div className="params-help">
      <button type="button" className="btn sm" onClick={() => setOpen((o) => !o)}>
        {open ? "▾" : "▸"} Params help — expected fields
      </button>
      {open && (
        <div className="params-help-body">
          <div className="params-help-top">
            <span className="muted">{kind.description}</span>
            {Object.keys(defaults).length > 0 && (
              <button type="button" className="btn sm btn-primary" onClick={() => onInsertDefaults(defaults)}>
                Insert defaults
              </button>
            )}
          </div>
          <div className="muted small">
            Default cron: <code>{kind.default_cron}</code> · Default name: <code>{kind.default_name}</code>
          </div>
          <div className="params-help-h">Expected fields</div>
          {kind.param_schema ? <SchemaFromSpec schema={kind.param_schema} /> : <div className="muted small">(accepts any JSON object)</div>}
          {kind.param_schema?.required && kind.param_schema.required.length > 0 && (
            <div className="muted small">
              <span className="schema-req">*</span> required
            </div>
          )}
          {Object.keys(defaults).length > 0 && (
            <>
              <div className="params-help-h">Example JSON</div>
              <pre className="params-example">{JSON.stringify(defaults, null, 2)}</pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function TestFetchResults({ result }: { result: TestFetchResult }) {
  return (
    <div className="test-results">
      <div className="test-results-h">Test fetch results</div>
      {result.sources.length === 0 && (
        <div className="muted small">
          No sources defined in params. Add at least one entry under <code>evvnt_sources</code>, <code>gcal_sources</code>, <code>json_sources</code>,{" "}
          <code>ical_sources</code>, <code>rss_sources</code>, <code>scraper_sources</code>, <code>sitemap_sources</code>, <code>listing_page_sources</code>,{" "}
          <code>deyra_schedule_sources</code>, <code>yodel_sources</code>, or <code>tribe_sources</code>.
        </div>
      )}
      {result.sources.map((s) => (
        <div key={`${s.source_type}-${s.name}-${s.url}`} className="test-source">
          <div className="test-source-h">
            <span className={`badge ${s.status === "ok" ? (s.event_count > 0 ? "ok" : "warn") : "bad"}`}>{s.status === "ok" ? `${s.event_count} events` : s.status}</span>
            <b>{s.name}</b>
            {s.source_type && <span className="code-chip">{s.source_type}</span>}
          </div>
          {s.url && <div className="test-source-url">{s.url}</div>}
          {s.error && <div className="test-source-err">{s.error}</div>}
          {s.sample_titles.length > 0 && (
            <ul className="test-samples">
              {s.sample_titles.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ul>
          )}
          {s.first_entry_fields && (
            <details className="test-diag">
              <summary>First-entry raw fields ({Object.keys(s.first_entry_fields).length})</summary>
              <table>
                <tbody>
                  {Object.entries(s.first_entry_fields).map(([k, v]) => (
                    <tr key={k}>
                      <td className="test-diag-k">{k}</td>
                      <td className="test-diag-v">{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
        </div>
      ))}
    </div>
  );
}
