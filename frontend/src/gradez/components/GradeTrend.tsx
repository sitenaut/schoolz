import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";
import { percentText, plural, scoreText } from "../format";
import { gradeTrend, lastGrade, weighsCategories } from "../gradeTrend";
import type { TrendDay } from "../gradeTrend";
import type { GradeEntry } from "../types";

const HEIGHT = 180;
const PAD = { top: 10, right: 44, bottom: 26, left: 40 };
// Dots at the ends stay inside the plot, not on its edge.
const INSET = 10;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function shortDate(iso: string): string {
  const [, m, d] = iso.split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}`;
}

function dayNumber(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Math.round(Date.UTC(y, m - 1, d) / 86400000);
}

/** The width the chart has, so text stays its real size at any width. A
 * callback ref, because the chart's box only exists once there are marks
 * to draw, which can be after the first render. */
function useWidth() {
  const [el, setEl] = useState<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!el) return;
    const measure = () => setWidth(el.clientWidth);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [el]);
  return [setEl, width] as const;
}

function summary(days: TrendDay[], marks: number): string {
  const graded = days.filter((d) => d.grade != null);
  const first = graded[0];
  const last = graded[graded.length - 1];
  const count = `${plural(marks, "graded assignment")}.`;
  if (!first || !last || first === last) return `Grade over time, ${count}`;
  return `Grade so far went from ${percentText(first.grade!)} on ${shortDate(first.date)} to ${percentText(last.grade!)} on ${shortDate(last.date)}, over ${count}`;
}

/** One class's marks in date order, and the grade they add up to. The
 * graded list under it on the class page is the same data as a table. */
export function GradeTrend({
  entries,
  genesisPercent,
  todayIso,
}: {
  entries: GradeEntry[];
  genesisPercent: number | null;
  todayIso: string;
}) {
  const [ref, width] = useWidth();
  const [active, setActive] = useState<number | null>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const [tipWidth, setTipWidth] = useState(0);
  // Measured before paint, so the readout lands inside the chart first time.
  useLayoutEffect(() => {
    if (tipRef.current) setTipWidth(tipRef.current.offsetWidth);
  }, [active, width]);
  const days = gradeTrend(entries, todayIso);
  const markCount = days.reduce((n, d) => n + d.marks.length, 0);
  // One day of marks is a score, not a trend: the list below already says it.
  if (days.length < 2) return null;

  const hasMissing = days.some((d) => d.marks.some((m) => m.missing));
  const weighted = weighsCategories(days, genesisPercent);
  const end = lastGrade(days);

  const top = Math.max(100, ...days.flatMap((d) => d.marks.map((m) => m.percent)));
  const yMax = Math.ceil(top / 50) * 50;
  const ticks = Array.from({ length: yMax / 50 + 1 }, (_, i) => i * 50);
  const plotW = Math.max(0, width - PAD.left - PAD.right);
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const first = dayNumber(days[0].date);
  const span = dayNumber(days[days.length - 1].date) - first || 1;
  const x = (iso: string) => PAD.left + INSET + ((dayNumber(iso) - first) / span) * Math.max(0, plotW - 2 * INSET);
  const y = (pct: number) => PAD.top + plotH - (Math.max(0, pct) / yMax) * plotH;

  const line = days.filter((d) => d.grade != null);
  const path = line.map((d, i) => `${i ? "L" : "M"}${x(d.date).toFixed(1)},${y(d.grade!).toFixed(1)}`).join("");
  const lastPoint = line[line.length - 1];

  const nearest = (clientX: number, rect: DOMRect) => {
    const px = clientX - rect.left;
    let best = 0;
    days.forEach((d, i) => {
      if (Math.abs(x(d.date) - px) < Math.abs(x(days[best].date) - px)) best = i;
    });
    return best;
  };
  const onPointer = (e: PointerEvent<SVGRectElement>) => setActive(nearest(e.clientX, e.currentTarget.ownerSVGElement!.getBoundingClientRect()));
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      e.preventDefault();
      const step = e.key === "ArrowRight" ? 1 : -1;
      setActive((a) => Math.min(days.length - 1, Math.max(0, (a ?? (step > 0 ? -1 : days.length)) + step)));
    } else if (e.key === "Escape") {
      setActive(null);
    }
  };

  const shown = active != null ? days[active] : null;
  const crossX = shown ? x(shown.date) : 0;
  // Beside the crosshair, right then left, and never past the chart's edge.
  const tipX =
    crossX + 10 + tipWidth <= width
      ? crossX + 10
      : crossX - 10 - tipWidth >= 0
        ? crossX - 10 - tipWidth
        : Math.max(0, Math.min(width - tipWidth, crossX - tipWidth / 2));

  return (
    <section className="gz-section">
      <header className="gz-section-head">
        <h2>Grade over time</h2>
        <p>Each mark from Genesis, and the grade they add up to.</p>
      </header>
      <div className="gz-card gz-trend">
        <ul className="gz-trend-legend">
          <li>
            <span className="gz-trend-key-line" aria-hidden="true" />
            Grade so far
          </li>
          <li>
            <span className="gz-trend-key-dot" aria-hidden="true" />
            Each assignment
          </li>
          {hasMissing && (
            <li>
              <span className="gz-trend-key-missing" aria-hidden="true" />
              Missing, counts as 0
            </li>
          )}
        </ul>
        <div
          ref={ref}
          className="gz-trend-plot"
          tabIndex={0}
          role="group"
          aria-label={`${summary(days, markCount)} Use the arrow keys to read each day.`}
          onKeyDown={onKey}
          onBlur={() => setActive(null)}
        >
          {width > 0 && (
            <svg width={width} height={HEIGHT} aria-hidden="true">
              {ticks.map((t) => (
                <g key={t}>
                  <line className="gz-trend-grid" x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)} />
                  <text className="gz-trend-tick" x={PAD.left - 8} y={y(t)} dy="0.32em" textAnchor="end">
                    {t}%
                  </text>
                </g>
              ))}
              <text className="gz-trend-tick" x={x(days[0].date)} y={HEIGHT - 6} textAnchor="start">
                {shortDate(days[0].date)}
              </text>
              <text className="gz-trend-tick" x={x(days[days.length - 1].date)} y={HEIGHT - 6} textAnchor="end">
                {shortDate(days[days.length - 1].date)}
              </text>
              {shown && <line className="gz-trend-cross" x1={crossX} x2={crossX} y1={PAD.top} y2={PAD.top + plotH} />}
              <path className="gz-trend-line" d={path} />
              {days.map((d, i) =>
                d.marks.map((m) => (
                  <circle
                    key={m.entry.external_uid}
                    className={m.missing ? "gz-trend-missing" : "gz-trend-dot"}
                    cx={x(d.date)}
                    cy={y(m.percent)}
                    r={i === active ? 5 : 4}
                  />
                )),
              )}
              {lastPoint && (
                <>
                  <circle className="gz-trend-end" cx={x(lastPoint.date)} cy={y(lastPoint.grade!)} r={4} />
                  <text className="gz-trend-end-label" x={x(lastPoint.date) + 9} y={y(lastPoint.grade!)} dy="0.32em">
                    {percentText(lastPoint.grade!)}
                  </text>
                </>
              )}
              <rect
                className="gz-trend-hit"
                x={0}
                y={0}
                width={width}
                height={HEIGHT}
                onPointerDown={onPointer}
                onPointerMove={onPointer}
                onPointerLeave={(e) => e.pointerType === "mouse" && setActive(null)}
              />
            </svg>
          )}
          {shown && (
            <div ref={tipRef} className="gz-trend-tip" style={{ left: tipX }} aria-live="polite">
              <p className="gz-trend-tip-date">{shortDate(shown.date)}</p>
              {shown.marks.map((m) => (
                <p key={m.entry.external_uid} className="gz-trend-tip-row">
                  <strong>{scoreText(m.entry)}</strong> {m.entry.title}
                </p>
              ))}
              {shown.grade != null && (
                <p className="gz-trend-tip-row">
                  <span className="gz-trend-key-line" aria-hidden="true" />
                  <strong>{percentText(shown.grade)}</strong> grade so far
                </p>
              )}
            </div>
          )}
        </div>
        {weighted && genesisPercent != null && end != null && (
          <p className="gz-note">
            Genesis gives some kinds of work more weight than others, so the class grade is {percentText(genesisPercent)}, not{" "}
            {percentText(end)}. The line adds up points only, so read it for which way the grade is heading.
          </p>
        )}
      </div>
    </section>
  );
}
