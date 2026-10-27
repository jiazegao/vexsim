import { useEffect, useMemo, useRef, useState } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { valueAt } from "../plots";
import { fixed } from "../pose";
import { onThemeChange } from "../theme";

const FONT = "11px system-ui, -apple-system, 'Segoe UI', sans-serif";

export interface LineSeries {
  label: string;
  values: readonly (number | null | undefined)[];
  slot: number | null; // a palette slot (1-8), or null: secondary ink (a reference)
  dash?: readonly number[];
  width?: number;
}

export interface RefLine {
  axis: "x" | "y";
  value: number;
  label: string;
}

export interface LineChartProps {
  title: string;
  unit: string; // the y axis's
  x: readonly number[];
  xUnit: string; // for the x axis's values ("s", "rpm", "in")
  series: LineSeries[];
  digits?: number; // of the values shown on hover
  height?: number;
  sync?: string; // charts with the same key share a crosshair
  yRange?: [number, number]; // fixed (small multiples share one)
  xRange?: [number, number];
  stepped?: boolean; // an ECDF: steps, not slopes
  refs?: RefLine[];
  testid?: string;
}

function useThemeVersion(): number {
  const [version, setVersion] = useState(0);
  useEffect(() => onThemeChange(() => setVersion((v) => v + 1)), []);
  return version;
}

/** A swatch of a series' line, for legends. */
export function LineSwatch(props: { slot: number | null; dash?: readonly number[] }) {
  return (
    <svg className="line-swatch" width="18" height="6" viewBox="0 0 18 6" aria-hidden="true">
      <line x1="0" y1="3" x2="18" y2="3" style={{ stroke: props.slot ? `var(--series-${props.slot})` : "var(--text-secondary)" }} strokeDasharray={props.dash ? props.dash.join(" ") : undefined} />
    </svg>
  );
}

/** One quantity (one unit, one axis) against another, for one or more series: a legend
 * when there are several, the values under the cursor as you hover. */
export function LineChart(props: LineChartProps) {
  const { title, unit, x, xUnit, series, height = 170, sync, yRange, xRange, stepped, refs } = props;
  const box = useRef<HTMLDivElement>(null);
  const at = useRef<HTMLSpanElement>(null);
  const values = useRef<(HTMLElement | null)[]>([]);
  const theme = useThemeVersion();
  const digits = props.digits ?? 2;
  const data = useMemo(() => [x, ...series.map((s) => s.values)] as unknown as uPlot.AlignedData, [x, series]);

  useEffect(() => {
    const element = box.current!;
    const style = getComputedStyle(document.documentElement);
    const token = (name: string) => style.getPropertyValue(name).trim();
    const muted = token("--text-muted");
    const grid = token("--gridline");
    const ink2 = token("--text-secondary");
    const show = (index: number | null) => {
      const xValue = index === null ? null : (x[index] ?? null);
      if (at.current) at.current.textContent = xValue === null ? "" : `at ${fixed(xValue, xDigits(x))} ${xUnit}`;
      series.forEach((s, i) => {
        const cell = values.current[i];
        if (cell) cell.textContent = xValue === null ? "" : fixed(valueAt(x as number[], s.values, xValue), digits);
      });
    };
    const drawRefs = (u: uPlot) => {
      if (!refs?.length) return;
      const ctx = u.ctx;
      ctx.save();
      ctx.strokeStyle = ink2;
      ctx.fillStyle = ink2;
      ctx.lineWidth = 1 * devicePixelRatio;
      ctx.setLineDash([4 * devicePixelRatio, 3 * devicePixelRatio]);
      ctx.font = `${11 * devicePixelRatio}px system-ui, sans-serif`;
      const { left, top, width, height: h } = u.bbox;
      for (const ref of refs) {
        ctx.beginPath();
        if (ref.axis === "y") {
          const y = u.valToPos(ref.value, "y", true);
          if (y < top || y > top + h) continue;
          ctx.moveTo(left, y);
          ctx.lineTo(left + width, y);
          ctx.stroke();
          ctx.textAlign = "right";
          ctx.textBaseline = "top"; // under the line: a line at the top of the plot leaves no room above
          ctx.fillText(ref.label, left + width - 4 * devicePixelRatio, y + 3 * devicePixelRatio);
        } else {
          const xp = u.valToPos(ref.value, "x", true);
          if (xp < left || xp > left + width) continue;
          ctx.moveTo(xp, top);
          ctx.lineTo(xp, top + h);
          ctx.stroke();
          ctx.textAlign = "left";
          ctx.textBaseline = "top";
          ctx.fillText(ref.label, xp + 4 * devicePixelRatio, top + 2 * devicePixelRatio);
        }
      }
      ctx.restore();
    };
    const u = new uPlot(
      {
        width: Math.max(160, element.clientWidth),
        height,
        legend: { show: false },
        padding: [8, 10, 0, 0],
        scales: {
          x: { time: false, ...(xRange ? { range: xRange } : {}) },
          y: yRange ? { range: yRange } : {},
        },
        cursor: { y: false, ...(sync ? { sync: { key: sync } } : {}), drag: { x: false, y: false }, points: { size: 7 } },
        axes: [
          {
            stroke: muted,
            font: FONT,
            size: 26,
            grid: { stroke: grid, width: 1 },
            ticks: { show: false },
            values: (_u, splits) => splits.map((v) => `${+v.toFixed(3)} ${xUnit}`),
          },
          { stroke: muted, font: FONT, size: 46, grid: { stroke: grid, width: 1 }, ticks: { show: false } },
        ],
        series: [
          {},
          ...series.map((s) => ({
            label: s.label,
            stroke: s.slot ? token(`--series-${s.slot}`) : ink2,
            width: s.width ?? 2,
            dash: s.dash ? [...s.dash] : undefined,
            points: { show: false },
            spanGaps: false,
            ...(stepped ? { paths: uPlot.paths.stepped!({ align: 1 }) } : {}),
          })),
        ],
        hooks: {
          setCursor: [(u) => show(u.cursor.idx ?? null)],
          draw: [drawRefs],
        },
      },
      data,
      element,
    );
    show(null);
    const observer = new ResizeObserver(() => {
      const width = Math.max(160, element.clientWidth);
      if (width !== u.width) u.setSize({ width, height });
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
      u.destroy();
    };
  }, [data, x, series, xUnit, height, sync, yRange, xRange, stepped, refs, theme, digits]);

  const many = series.length > 1;
  return (
    <figure className="plot chart" data-testid={props.testid}>
      <figcaption>
        <span className="plot-title">{title}</span> {unit && <span className="muted">({unit})</span>}
        {!many && <b className="num plot-value" ref={(el) => void (values.current[0] = el)} />}
        <span className="spacer" />
        <span className="muted small num" ref={at} />
      </figcaption>
      {many && (
        <div className="plot-legend">
          {series.map((s, i) => (
            <span className="plot-key" key={`${i}:${s.label}`}>
              <LineSwatch slot={s.slot} dash={s.dash} />
              <span className="plot-label" title={s.label}>
                {s.label}
              </span>
              <b className="num" ref={(el) => void (values.current[i] = el)} />
            </span>
          ))}
        </div>
      )}
      <div className="plot-canvas chart-canvas" ref={box} />
    </figure>
  );
}

/** Decimals worth showing for an axis's values. */
function xDigits(x: readonly number[]): number {
  const span = x.length > 1 ? Math.abs((x.at(-1) ?? 0) - (x[0] ?? 0)) : 1;
  return span >= 100 ? 0 : span >= 10 ? 1 : 2;
}
