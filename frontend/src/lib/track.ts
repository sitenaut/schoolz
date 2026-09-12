import { getFaro } from "./telemetry";

type Attrs = Record<string, string | number | boolean>;

function stringify(attrs?: Attrs): Record<string, string> | undefined {
  if (!attrs) return undefined;
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(attrs)) out[k] = String(v);
  return out;
}

/** No-ops when Faro isn't initialized (local dev, vitest, RUM disabled). */
export function trackEvent(name: string, attrs?: Attrs): void {
  getFaro()?.api.pushEvent(name, stringify(attrs));
}

/** valueMs: elapsed time in milliseconds for a "*_ready" measurement. */
export function trackMeasurement(type: string, valueMs: number, attrs?: Attrs): void {
  getFaro()?.api.pushMeasurement({ type, values: { value_ms: valueMs } }, { context: stringify(attrs) });
}
