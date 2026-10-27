import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import type { Point } from "../charts";
import { bounds, fit, niceStep } from "../charts";
import { fixed } from "../pose";
import { onThemeChange } from "../theme";
import type { View } from "../view";
import { toField, toScreen } from "../view";
import { LineSwatch } from "./LineChart";

export interface PathSeries {
  label: string;
  points: readonly Point[];
  slot: number | null; // a palette slot, or null: primary ink (the truth)
  dash?: readonly number[];
  width?: number;
  end?: boolean; // a dot where it ends
  key?: boolean; // in the legend (default: yes)
}

/** Paths on the floor, x and y at one scale, on an inch grid; where it starts as a square.
 * Hover for the point under the cursor. */
export function PathChart(props: { title: string; paths: PathSeries[]; start?: Point; height?: number; note?: ReactNode; testid?: string }) {
  const { title, paths, start, height = 360 } = props;
  const canvas = useRef<HTMLCanvasElement>(null);
  const view = useRef<View | null>(null);
  const [cursor, setCursor] = useState<Point | null>(null);
  const [theme, setTheme] = useState(0);
  useEffect(() => onThemeChange(() => setTheme((v) => v + 1)), []);

  useEffect(() => {
    const element = canvas.current!;
    const draw = () => {
      const width = element.clientWidth;
      const ratio = window.devicePixelRatio || 1;
      element.width = Math.round(width * ratio);
      element.height = Math.round(height * ratio);
      const ctx = element.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      const style = getComputedStyle(document.documentElement);
      const token = (name: string) => style.getPropertyValue(name).trim();
      ctx.clearRect(0, 0, width, height);
      const box = bounds([...paths.map((p) => p.points), ...(start ? [[start]] : [])]);
      if (!box) return;
      const v = fit(box, width, height);
      view.current = v;

      // the grid, with its inches at the left and the bottom
      const [left, top] = toField(v, 0, 0);
      const [right, bottom] = toField(v, width, height);
      const step = niceStep(Math.max(right - left, top - bottom), 8);
      ctx.lineWidth = 1;
      ctx.strokeStyle = token("--gridline");
      ctx.fillStyle = token("--text-muted");
      ctx.font = "11px system-ui, -apple-system, 'Segoe UI', sans-serif";
      for (let x = Math.ceil(left / step) * step; x <= right; x += step) {
        const [px] = toScreen(v, x, 0);
        ctx.beginPath();
        ctx.moveTo(Math.round(px) + 0.5, 0);
        ctx.lineTo(Math.round(px) + 0.5, height);
        ctx.stroke();
        ctx.textAlign = "center";
        if (px > 16 && px < width - 16) ctx.fillText(`${+x.toFixed(3)}`, px, height - 4);
      }
      for (let y = Math.ceil(bottom / step) * step; y <= top; y += step) {
        const [, py] = toScreen(v, 0, y);
        ctx.beginPath();
        ctx.moveTo(0, Math.round(py) + 0.5);
        ctx.lineTo(width, Math.round(py) + 0.5);
        ctx.stroke();
        ctx.textAlign = "left";
        if (py > 14 && py < height - 18) ctx.fillText(`${+y.toFixed(3)}`, 4, py - 3);
      }

      const surface = token("--surface-1");
      for (const path of paths) {
        if (path.points.length === 0) continue;
        const color = path.slot ? token(`--series-${path.slot}`) : token("--text-primary");
        ctx.strokeStyle = color;
        ctx.lineWidth = path.width ?? 2;
        ctx.lineJoin = "round";
        ctx.setLineDash(path.dash ? [...path.dash] : []);
        ctx.beginPath();
        path.points.forEach(([x, y], i) => {
          const [px, py] = toScreen(v, x, y);
          if (i === 0) ctx.moveTo(px, py);
          else ctx.lineTo(px, py);
        });
        ctx.stroke();
        ctx.setLineDash([]);
        if (path.end) {
          const [x, y] = path.points[path.points.length - 1];
          const [px, py] = toScreen(v, x, y);
          ctx.beginPath();
          ctx.arc(px, py, 4.5, 0, 2 * Math.PI);
          ctx.fillStyle = color;
          ctx.strokeStyle = surface;
          ctx.lineWidth = 2;
          ctx.fill();
          ctx.stroke();
        }
      }
      if (start) {
        const [px, py] = toScreen(v, start[0], start[1]);
        ctx.fillStyle = token("--text-secondary");
        ctx.strokeStyle = surface;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.rect(px - 4, py - 4, 8, 8);
        ctx.fill();
        ctx.stroke();
      }
    };
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(element);
    return () => observer.disconnect();
  }, [paths, start, height, theme]);

  const keyed = paths.filter((p) => p.key !== false);
  return (
    <figure className="plot chart path-chart" data-testid={props.testid}>
      <figcaption>
        <span className="plot-title">{title}</span> <span className="muted">(in)</span>
        <span className="spacer" />
        <span className="muted small num">{cursor ? `x ${fixed(cursor[0], 1)}, y ${fixed(cursor[1], 1)} in` : ""}</span>
      </figcaption>
      {keyed.length > 1 && (
        <div className="plot-legend">
          {keyed.map((p, i) => (
            <span className="plot-key" key={`${i}:${p.label}`}>
              {p.slot === null ? <TruthSwatch /> : <LineSwatch slot={p.slot} dash={p.dash} />}
              <span className="plot-label" title={p.label}>
                {p.label}
              </span>
            </span>
          ))}
          {start && (
            <span className="plot-key">
              <span className="start-swatch" aria-hidden="true" /> start
            </span>
          )}
        </div>
      )}
      <canvas
        ref={canvas}
        className="path-canvas"
        style={{ height }}
        onPointerMove={(event) => {
          const v = view.current;
          if (!v) return;
          const rect = event.currentTarget.getBoundingClientRect();
          setCursor(toField(v, event.clientX - rect.left, event.clientY - rect.top));
        }}
        onPointerLeave={() => setCursor(null)}
      />
      {props.note}
    </figure>
  );
}

function TruthSwatch() {
  return (
    <svg className="line-swatch" width="18" height="6" viewBox="0 0 18 6" aria-hidden="true">
      <line x1="0" y1="3" x2="18" y2="3" style={{ stroke: "var(--text-primary)", strokeWidth: 2.5 }} />
    </svg>
  );
}
