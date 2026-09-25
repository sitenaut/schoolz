import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { Badge } from "../components/ui/Badge";
import { Field } from "../components/ui/Field";
import { SectionCard } from "../components/ui/SectionCard";
import { Switch } from "../components/ui/Switch";
import { useToast } from "../components/ui/Toast";

type AudienceConfig = {
  provider: string;
  model: string;
  escalation_model: string | null;
  reasoning_effort: string | null;
};
type ModelPrice = { input: number; output: number; cache_read: number | null };
type Settings = { anonymous: AudienceConfig; signed_in: AudienceConfig; prices: Record<string, ModelPrice> };
type Provider = { name: string; configured: boolean };
type CompareResult = {
  provider: string;
  requested_model: string;
  model: string | null;
  escalated: boolean;
  reply: string | null;
  error: string | null;
  rounds: number;
  tools_called: string[];
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cost_usd: number | null;
  latency_ms: number;
};

const PROVIDER_LABEL: Record<string, string> = { anthropic: "Anthropic (Claude)", gemini: "Google (Gemini)" };
const EFFORTS = ["", "minimal", "low", "medium", "high"];

async function errorText(res: Response): Promise<string> {
  const body = await res.json().catch(() => null);
  return body?.detail ? String(body.detail) : `Request failed (${res.status})`;
}

/** Admin -> Chatbot: which provider/model the public assistant runs on for
 * anonymous visitors and for signed-in users (backend/routers/admin_chatbot.py),
 * the price table behind cost estimates, and a side-by-side compare that
 * runs one question through up to three configurations with the real tools. */
export function ChatbotAdminPage() {
  const toast = useToast();
  const [settings, setSettings] = useState<Settings | null>(null);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [models, setModels] = useState<Record<string, string[]>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    apiFetch("/admin/chatbot")
      .then(async (r) => {
        if (!r.ok) throw new Error(await errorText(r));
        const body = await r.json();
        setSettings(body.settings);
        setProviders(body.providers);
        for (const p of body.providers as Provider[]) {
          if (!p.configured) continue;
          apiFetch(`/admin/chatbot/models?provider=${p.name}`)
            .then((mr) => (mr.ok ? mr.json() : []))
            .then((list: string[]) => setModels((cur) => ({ ...cur, [p.name]: list })))
            .catch(() => undefined);
        }
      })
      .catch((e) => setLoadError(e instanceof Error ? e.message : "Couldn't load chatbot settings."));
  }, []);

  const save = async () => {
    if (!settings) return;
    setSaving(true);
    try {
      const res = await apiFetch("/admin/chatbot", { method: "PUT", body: JSON.stringify(settings) });
      if (!res.ok) throw new Error(await errorText(res));
      setSettings((await res.json()).settings);
      toast({ title: "Chatbot settings saved", description: "Live within about 30 seconds.", tone: "ok" });
    } catch (e) {
      toast({ title: "Couldn't save", description: e instanceof Error ? e.message : undefined, tone: "bad" });
    } finally {
      setSaving(false);
    }
  };

  if (loadError) return <div className="chat-error">{loadError}</div>;
  if (!settings) return <p className="muted">Loading…</p>;

  const setAudience = (key: "anonymous" | "signed_in", next: AudienceConfig) => setSettings({ ...settings, [key]: next });
  const allModels = Object.values(models).flat();

  return (
    <div className="cb-admin">
      <datalist id="cb-models">
        {allModels.map((m) => (
          <option key={m} value={m} />
        ))}
      </datalist>

      <SectionCard
        title="Live settings"
        description="What the assistant runs on right now. Changes take effect within about 30 seconds."
        footer={
          <button className="btn btn-primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save all changes"}
          </button>
        }
      >
        <div className="cb-grid">
          <AudienceEditor
            title="Anonymous visitors"
            value={settings.anonymous}
            providers={providers}
            onChange={(v) => setAudience("anonymous", v)}
          />
          <AudienceEditor
            title="Signed-in users"
            value={settings.signed_in}
            providers={providers}
            onChange={(v) => setAudience("signed_in", v)}
            privacyNote
          />
        </div>
      </SectionCard>

      <SectionCard
        title="Prices"
        description="$ per million tokens, used only for the compare panel's cost estimates. Cache writes are counted at 1.25× input. Fill in Gemini's from Google's pricing page — unpriced models show no cost rather than a guess."
        footer={
          <button className="btn btn-primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save all changes"}
          </button>
        }
      >
        <PriceTable prices={settings.prices} onChange={(prices) => setSettings({ ...settings, prices })} />
      </SectionCard>

      <ComparePanel settings={settings} providers={providers} />
    </div>
  );
}

function AudienceEditor({
  title,
  value,
  providers,
  onChange,
  privacyNote,
}: {
  title: string;
  value: AudienceConfig;
  providers: Provider[];
  onChange: (v: AudienceConfig) => void;
  privacyNote?: boolean;
}) {
  return (
    <div className="cb-col">
      <div className="cb-col-h">{title}</div>
      <ConfigFields value={value} providers={providers} onChange={onChange} />
      {privacyNote && value.provider !== "anthropic" && (
        <p className="small cb-warn">
          Signed-in conversations send a family's children's names, grades and schedules to this provider. Use a paid API tier
          whose terms don't allow training on your data.
        </p>
      )}
    </div>
  );
}

function ConfigFields({ value, providers, onChange }: { value: AudienceConfig; providers: Provider[]; onChange: (v: AudienceConfig) => void }) {
  return (
    <>
      <Field label="Provider">
        <select value={value.provider} onChange={(e) => onChange({ ...value, provider: e.target.value })}>
          {providers.map((p) => (
            <option key={p.name} value={p.name} disabled={!p.configured}>
              {PROVIDER_LABEL[p.name] ?? p.name}
              {p.configured ? "" : " — no API key on server"}
            </option>
          ))}
        </select>
      </Field>
      <Field label="Model" hint="Type or pick from the provider's list.">
        <input list="cb-models" value={value.model} onChange={(e) => onChange({ ...value, model: e.target.value })} />
      </Field>
      <Field label="Escalation model" hint="Used once a question needs several lookups. Blank = never escalate.">
        <input
          list="cb-models"
          value={value.escalation_model ?? ""}
          onChange={(e) => onChange({ ...value, escalation_model: e.target.value.trim() || null })}
        />
      </Field>
      {value.provider !== "anthropic" && (
        <Field label="Reasoning effort" hint="Gemini's thinking counts against its output budget; low keeps replies from coming back empty.">
          <select value={value.reasoning_effort ?? ""} onChange={(e) => onChange({ ...value, reasoning_effort: e.target.value || null })}>
            {EFFORTS.map((x) => (
              <option key={x} value={x}>
                {x || "provider default"}
              </option>
            ))}
          </select>
        </Field>
      )}
    </>
  );
}

function PriceTable({ prices, onChange }: { prices: Record<string, ModelPrice>; onChange: (p: Record<string, ModelPrice>) => void }) {
  const [newModel, setNewModel] = useState("");
  const num = (s: string) => (s.trim() === "" ? null : Number(s));
  const update = (model: string, patch: Partial<ModelPrice>) => onChange({ ...prices, [model]: { ...prices[model], ...patch } });

  return (
    <div className="cb-prices">
      <table className="cb-table">
        <thead>
          <tr>
            <th>Model</th>
            <th>Input</th>
            <th>Output</th>
            <th>Cache read</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {Object.entries(prices).map(([model, p]) => (
            <tr key={model}>
              <td className="mono">{model}</td>
              <td>
                <input type="number" min={0} step="0.01" value={p.input} onChange={(e) => update(model, { input: num(e.target.value) ?? 0 })} />
              </td>
              <td>
                <input type="number" min={0} step="0.01" value={p.output} onChange={(e) => update(model, { output: num(e.target.value) ?? 0 })} />
              </td>
              <td>
                <input
                  type="number"
                  min={0}
                  step="0.001"
                  value={p.cache_read ?? ""}
                  placeholder="= input"
                  onChange={(e) => update(model, { cache_read: num(e.target.value) })}
                />
              </td>
              <td>
                <button
                  className="btn icon danger"
                  aria-label={`Remove ${model}`}
                  onClick={() => {
                    const next = { ...prices };
                    delete next[model];
                    onChange(next);
                  }}
                >
                  ×
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="cb-add">
        <input list="cb-models" placeholder="Add a model…" value={newModel} onChange={(e) => setNewModel(e.target.value)} />
        <button
          className="btn sm"
          disabled={!newModel.trim() || newModel.trim() in prices}
          onClick={() => {
            onChange({ ...prices, [newModel.trim()]: { input: 0, output: 0, cache_read: null } });
            setNewModel("");
          }}
        >
          Add
        </button>
      </div>
    </div>
  );
}

function ComparePanel({ settings, providers }: { settings: Settings; providers: Provider[] }) {
  const gemini = providers.find((p) => p.name === "gemini");
  const [configs, setConfigs] = useState<AudienceConfig[]>(() => [
    { ...settings.anonymous },
    gemini?.configured
      ? { provider: "gemini", model: "", escalation_model: null, reasoning_effort: "low" }
      : { ...settings.signed_in },
  ]);
  const [message, setMessage] = useState("What's going on this weekend that I can take the kids to?");
  const [signedIn, setSignedIn] = useState(false);
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<CompareResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setRunning(true);
    setError(null);
    setResults(null);
    try {
      const res = await apiFetch("/admin/chatbot/compare", {
        method: "POST",
        body: JSON.stringify({ message, signed_in: signedIn, configs }),
      });
      if (!res.ok) throw new Error(await errorText(res));
      setResults(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Compare failed.");
    } finally {
      setRunning(false);
    }
  };

  const money = (n: number | null) => (n == null ? "no price on file" : `$${n < 0.01 ? n.toFixed(5) : n.toFixed(4)}`);

  return (
    <SectionCard
      title="Compare"
      description="Runs one question through each configuration with the real tools, side by side. Each run costs real money on that provider."
    >
      <Field label="Question">
        <textarea rows={2} value={message} onChange={(e) => setMessage(e.target.value)} maxLength={2000} />
      </Field>
      <div className="cb-row">
        <Switch checked={signedIn} onChange={setSignedIn} label="Ask as me (signed in)" />
        <span className="small muted">
          {signedIn
            ? "Asking as you (signed in) — your children's data goes to each provider compared."
            : "Asking as an anonymous visitor (public tools only). Switch on to ask as you, signed in."}
        </span>
      </div>

      <div className="cb-grid">
        {configs.map((c, i) => (
          <div className="cb-col" key={i}>
            <div className="cb-col-h">
              {String.fromCharCode(65 + i)}
              {configs.length > 1 && (
                <button className="btn icon" aria-label="Remove" onClick={() => setConfigs(configs.filter((_, j) => j !== i))}>
                  ×
                </button>
              )}
            </div>
            <ConfigFields value={c} providers={providers} onChange={(v) => setConfigs(configs.map((x, j) => (j === i ? v : x)))} />
          </div>
        ))}
      </div>
      <div className="cb-row">
        {configs.length < 3 && (
          <button className="btn sm" onClick={() => setConfigs([...configs, { ...configs[configs.length - 1] }])}>
            Add a column
          </button>
        )}
        <button className="btn btn-primary" onClick={run} disabled={running || !message.trim() || configs.some((c) => !c.model.trim())}>
          {running ? "Running…" : "Run compare"}
        </button>
      </div>

      {error && <div className="chat-error">{error}</div>}
      {results && (
        <div className="cb-grid cb-results">
          {results.map((r, i) => (
            <div className="cb-col" key={i}>
              <div className="cb-col-h">
                {String.fromCharCode(65 + i)} · {PROVIDER_LABEL[r.provider] ?? r.provider}
              </div>
              <div className="small mono">
                {r.model ?? r.requested_model}
                {r.escalated && (
                  <>
                    {" "}
                    <Badge tone="warn">escalated</Badge>
                  </>
                )}
              </div>
              {r.error ? <div className="chat-error">{r.error}</div> : <div className="cb-reply">{r.reply}</div>}
              <dl className="cb-stats">
                <dt>Cost</dt>
                <dd>{money(r.cost_usd)}</dd>
                <dt>Time</dt>
                <dd>{(r.latency_ms / 1000).toFixed(1)}s</dd>
                <dt>Tokens</dt>
                <dd>
                  {r.input_tokens.toLocaleString()} in · {r.cache_read_tokens.toLocaleString()} cached · {r.output_tokens.toLocaleString()} out
                </dd>
                <dt>Tools</dt>
                <dd>{r.tools_called.length ? r.tools_called.join(", ") : "none"}</dd>
              </dl>
            </div>
          ))}
        </div>
      )}
    </SectionCard>
  );
}
