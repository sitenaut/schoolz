import { useEffect, useState } from "react";
import { apiFetch } from "../api";
import { IconShield } from "./icons";
import { SectionCard } from "./ui/SectionCard";
import { useToast } from "./ui/Toast";

type Device = {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
};

/** Computers whose Backpack Capture was connected to this account
 * (/connect). Each can only send pages; removing one disconnects it at once.
 * Nothing shows until there's something to list. */
export function ConnectedComputersCard() {
  const toast = useToast();
  const [devices, setDevices] = useState<Device[]>([]);

  useEffect(() => {
    apiFetch("/capture-devices")
      .then((r) => (r.ok ? r.json() : []))
      .then(setDevices)
      .catch(() => setDevices([]));
  }, []);

  if (!devices.length) return null;

  const remove = async (device: Device) => {
    const r = await apiFetch(`/capture-devices/${encodeURIComponent(device.id)}`, { method: "DELETE" });
    if (!r.ok) {
      toast({ title: "Couldn't disconnect it", tone: "bad" });
      return;
    }
    setDevices((cur) => cur.filter((d) => d.id !== device.id));
    toast({ title: "Disconnected", tone: "ok" });
  };

  const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });

  return (
    <SectionCard
      title="Backpack Capture"
      description="Computers whose Backpack Capture sends your children's schoolwork here. It can't do anything else."
      icon={<IconShield />}
    >
      {devices.map((d) => (
        <div className="info-row" key={d.id}>
          <span className="ico">
            <IconShield />
          </span>
          <div className="txt">
            <b>{d.name}</b>
            <small>
              Connected {day(d.created_at)} · {d.last_used_at ? `last used ${day(d.last_used_at)}` : "not used yet"}
            </small>
          </div>
          <button className="btn sm" onClick={() => remove(d)}>
            Disconnect
          </button>
        </div>
      ))}
    </SectionCard>
  );
}
