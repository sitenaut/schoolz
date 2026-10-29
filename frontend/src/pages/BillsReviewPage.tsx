import { useCallback, useEffect, useState } from "react";
import { Badge } from "../components/ui/Badge";
import { PageHeader } from "../components/ui/PageHeader";
import { SectionCard } from "../components/ui/SectionCard";
import { useToast } from "../components/ui/Toast";
import {
  type DisputedBill,
  type HeldBill,
  type ReviewQueue,
  billImageUrl,
  decideBill,
  dollars,
  fetchReviewQueue,
  unpauseGiver,
} from "../lib/bills";

const REJECT_REASONS: [string, string][] = [
  ["not_their_bill", "Not the requester's own bill"],
  ["not_residential", "A business account"],
  ["unreadable", "Couldn't be checked"],
  ["other", "Something else didn't check out"],
];

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "-");
const show = (v: unknown) => (v === null || v === undefined || v === "" ? "(none)" : String(v));

/** /admin/bills - Neighborz review: bills a check held (the image shows a
 * name and address: look, decide, and it's deleted), payments a requester
 * says never arrived, and givers whose holding is paused. */
export function BillsReviewPage() {
  const toast = useToast();
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    fetchReviewQueue()
      .then(setQueue)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed"));
  }, []);
  useEffect(load, [load]);

  const act = async (fn: () => Promise<unknown>, done: string) => {
    try {
      await fn();
      toast({ title: done, tone: "ok" });
      load();
    } catch (err) {
      toast({ title: err instanceof Error ? err.message : "Failed", tone: "bad" });
    }
  };

  return (
    <div>
      <PageHeader
        title="Neighborz review"
        subtitle="Held bills, disputed payments and paused givers. Names never appear here; a bill image may show one, so look only as long as you need to."
      />
      {error && <p className="bills-error">{error}</p>}
      {queue && (
        <>
          <SectionCard title={`Held bills (${queue.held.length})`} description="A check in code held these. Compare what was read with what was posted, against the bill.">
            {queue.held.length === 0 ? (
              <p className="muted">Nothing waiting.</p>
            ) : (
              queue.held.map((b) => (
                <HeldCard
                  key={b.id}
                  bill={b}
                  onApprove={() => act(() => decideBill(b.id, "approve"), "Listed")}
                  onReject={(reason) => act(() => decideBill(b.id, "reject", reason), "Rejected; the requester is told")}
                />
              ))
            )}
          </SectionCard>

          <SectionCard
            title={`Disputed payments (${queue.disputed.length})`}
            description="The giver says they paid; the requester says it hasn't arrived. Neither side can be checked with the utility from here."
          >
            {queue.disputed.length === 0 ? (
              <p className="muted">Nothing waiting.</p>
            ) : (
              queue.disputed.map((d) => (
                <DisputeCard
                  key={d.hold_id}
                  dispute={d}
                  onRelist={() => act(() => decideBill(d.bill_id, "relist"), "Back on the list; the giver has a strike")}
                  onClose={() => act(() => decideBill(d.bill_id, "close_paid"), "Closed as paid")}
                />
              ))
            )}
          </SectionCard>

          <SectionCard title={`Paused givers (${queue.paused.length})`} description="Two strikes (holds that ran out, or disputes decided against them) in 90 days.">
            {queue.paused.length === 0 ? (
              <p className="muted">Nobody is paused.</p>
            ) : (
              <ul className="bills-review-list">
                {queue.paused.map((p) => (
                  <li key={p.giver_id}>
                    <code>{p.giver_id.slice(0, 8)}</code> <Badge tone="warn">{p.strikes} strikes</Badge>{" "}
                    <button type="button" className="btn" onClick={() => act(() => unpauseGiver(p.giver_id), "Pause lifted")}>
                      Lift pause
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
        </>
      )}
    </div>
  );
}

function HeldCard({ bill, onApprove, onReject }: { bill: HeldBill; onApprove: () => void; onReject: (reason: string) => void }) {
  const [image, setImage] = useState<{ url: string; type: string } | null>(null);
  const [reason, setReason] = useState(REJECT_REASONS[0][0]);

  useEffect(() => () => {
    if (image) URL.revokeObjectURL(image.url);
  }, [image]);

  const showImage = async () => {
    try {
      setImage(await billImageUrl(bill.id));
    } catch {
      setImage(null);
    }
  };

  const rows: [string, unknown, unknown][] = [
    ["Account number", bill.read.account_number, bill.account_number],
    ["Service ZIP", bill.read.service_zip, bill.service_zip],
    ["Amount due", bill.read.amount_due, dollars(bill.amount_due_cents)],
    ["Asked for", "", dollars(bill.amount_cents)],
    ["Due date", bill.read.due_date, bill.due_date],
    ["Company", bill.read.company, ""],
    ["Residential", bill.read.residential, ""],
    ["Shutoff notice", bill.read.shutoff_notice, bill.shutoff_notice],
  ];

  return (
    <div className="bills-review-card">
      <div className="bills-review-flags">
        {bill.flag_text.map((f) => (
          <Badge key={f} tone="warn">
            {f}
          </Badge>
        ))}
        {bill.requester_disputes > 0 && <Badge tone="bad">{bill.requester_disputes} disputes in 90 days</Badge>}
        <span className="muted">Posted {when(bill.posted_at)}</span>
      </div>
      <table className="bills-review-table">
        <thead>
          <tr>
            <th />
            <th>Read from the bill</th>
            <th>Posted</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, read, posted]) => (
            <tr key={label}>
              <th>{label}</th>
              <td>{show(read)}</td>
              <td>{show(posted)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {bill.has_image &&
        (image ? (
          image.type === "application/pdf" ? (
            <a className="btn" href={image.url} download="bill.pdf">
              Download the PDF
            </a>
          ) : (
            <img className="bills-review-image" src={image.url} alt="The uploaded bill" />
          )
        ) : (
          <button type="button" className="btn" onClick={showImage}>
            Show the bill
          </button>
        ))}
      <div className="bills-actions">
        <button type="button" className="btn btn-primary" onClick={onApprove}>
          List it
        </button>
        <select value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Reason">
          {REJECT_REASONS.map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <button type="button" className="btn btn-danger" onClick={() => onReject(reason)}>
          Reject
        </button>
      </div>
    </div>
  );
}

function DisputeCard({ dispute, onRelist, onClose }: { dispute: DisputedBill; onRelist: () => void; onClose: () => void }) {
  return (
    <div className="bills-review-card">
      <table className="bills-review-table">
        <tbody>
          <tr>
            <th>Asked / paid</th>
            <td>
              {dollars(dispute.amount_cents)} / {dollars(dispute.paid_cents)} on {show(dispute.paid_on)}
            </td>
          </tr>
          <tr>
            <th>Confirmation number</th>
            <td>
              <code>{show(dispute.confirmation_number)}</code>
            </td>
          </tr>
          <tr>
            <th>Reported / disputed</th>
            <td>
              {when(dispute.reported_at)} / {when(dispute.disputed_at)}
            </td>
          </tr>
          <tr>
            <th>Giver</th>
            <td>
              {dispute.giver_strikes} strikes, {dispute.giver_reveals_90d} account numbers seen in 90 days
            </td>
          </tr>
          <tr>
            <th>Requester</th>
            <td>{dispute.requester_disputes} disputes in 90 days</td>
          </tr>
        </tbody>
      </table>
      <div className="bills-actions">
        <button type="button" className="btn" onClick={onRelist}>
          Put it back on the list (giver strike)
        </button>
        <button type="button" className="btn btn-primary" onClick={onClose}>
          Close as paid
        </button>
      </div>
    </div>
  );
}
