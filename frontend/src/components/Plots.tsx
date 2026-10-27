import { useEffect, useMemo, useRef, useState } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import type { Playhead } from "../playhead";
import type { ChartSpec, RunColumns, SeriesSpec } from "../plots";
import { chartData, chartsFor, valueAt } from "../plots";
import { fixed } from "../pose";
import type { Telemetry } from "../protocol";
import type { Recording } from "../recording";
import { COMPARE_DASHES, telemetryOf } from "../recording";
import { onThemeChange } from "../theme";

const SYNC_KEY = "vexsim-plots"; // the crosshair moves in every chart at once
const HEIGHT = 150; // px, plotting area and axes
const DIGITS: Record<string, number> = { in: 2, "°": 1, "in/s": 1, "°/s": 0, V: 2, A: 2, "°C": 0 };
const FONT = "11px system-ui, -apple-system, 'Segoe UI', sans-serif";

/** The telemetry of each recording, as it arrives: a key's columns, or why they didn't come. */
function useTelemetry(runs: Recording[]): Map<string, Telemetry | string> {
  const [loaded, setLoaded] = useState<Map<string, Telemetry | string>>(() => new Map());
  const asked = useRef(new Set<string>());
  useEffect(() => {
    for (const run of runs) {
      if (asked.current.has(run.key)) continue;
      asked.current.add(run.key);
      telemetryOf(run).then(
        (telemetry) => setLoaded((map) => new Map(map).set(run.key, telemetry)),
        (error: Error) => {
          asked.current.delete(run.key);
          setLoaded((map) => new Map(map).set(run.key, error.message));
        },
      );
    }
  }, [runs]);
  return loaded;
}

function useThemeVersion(): number {
  const [version, setVersion] = useState(0);
  useEffect(() => onThemeChange(() => setVersion((v) => v + 1)), []);
  return version;
}

/** Charts of the shown run's telemetry, and of the compared runs where a chart has a single
 * quantity. Hover for the values at a moment (in every chart at once); click to go there. */
export function Plots(props: { shown: Recording; compared: Recording[]; playhead: Playhead }) {
  const { shown, compared, playhead } = props;
  const runs = useMemo(() => [shown, ...compared], [shown, compared]);
  const telemetry = useTelemetry(runs);
  const theme = useThemeVersion();
  const mechanisms = useMemo(() => shown.playback.tape.scene.robot.mechanisms.map((m) => m.name), [shown]);

  const columns = useMemo(() => {
    if (typeof telemetry.get(shown.key) !== "object") return [];
    const found: RunColumns[] = [];
    runs.forEach((run, i) => {
      const t = telemetry.get(run.key);
      if (typeof t === "object") found.push({ name: run.label, telemetry: t, dash: i === 0 ? undefined : COMPARE_DASHES[i - 1] });
    });
    return found;
  }, [runs, telemetry, shown]);
  const charts = useMemo(() => chartsFor(columns, mechanisms), [columns, mechanisms]);
  const range = useMemo((): [number, number] => {
    const times = columns.flatMap((c) => {
      const t = c.telemetry.columns.time_s ?? [];
      return t.length ? [t[0] ?? 0, t.at(-1) ?? 0] : [];
    });
    return times.length ? [Math.min(...times), Math.max(...times, Math.min(...times) + 0.1)] : [0, 1];
  }, [columns]);

  const state = telemetry.get(shown.key);
  if (typeof state === "string") return <div className="plots-empty">The run's telemetry didn't load: {state}</div>;
  if (!state) return <div className="plots-empty">Loading the run's telemetry…</div>;
  return (
    <div className="plots" data-testid="plots">
      {charts.map((chart) => (
        <Chart key={`${chart.id}:${chart.series.map((s) => `${s.run}${s.column}`).join(",")}`} spec={chart} runs={columns} range={range} playhead={playhead} theme={theme} />
      ))}
    </div>
  );
}

function LineSwatch(props: { series: SeriesSpec }) {
  const { slot, dash } = props.series;
  return (
    <svg className="line-swatch" width="18" height="6" viewBox="0 0 18 6" aria-hidden="true">
      <line x1="0" y1="3" x2="18" y2="3" style={{ stroke: slot ? `var(--series-${slot})` : "var(--text-secondary)" }} strokeDasharray={dash ? dash.join(" ") : undefined} />
    </svg>
  );
}

function Chart(props: { spec: ChartSpec; runs: RunColumns[]; range: [number, number]; playhead: Playhead; theme: number }) {
  const { spec, runs, range, playhead, theme } = props;
  const box = useRef<HTMLDivElement>(null);
  const at = useRef<HTMLSpanElement>(null);
  const values = useRef<(HTMLElement | null)[]>([]);
  const data = useMemo(() => chartData(spec, runs), [spec, runs]);
  const digits = DIGITS[spec.unit] ?? 2;

  useEffect(() => {
    const element = box.current!;
    const style = getComputedStyle(document.documentElement);
    const token = (name: string) => style.getPropertyValue(name).trim();
    const muted = token("--text-muted");
    const grid = token("--gridline");
    let hovering = false;

    const show = (t: number) => {
      if (at.current) at.current.textContent = `at ${t.toFixed(2)} s`;
      spec.series.forEach((_, i) => {
        const cell = values.current[i];
        if (cell) cell.textContent = fixed(valueAt(data[0], data[i + 1], t), digits);
      });
    };
    const line = document.createElement("div");
    line.className = "playhead-line";
    const place = (u: uPlot) => {
      const x = u.valToPos(playhead.t, "x");
      line.style.transform = `translateX(${Math.round(x)}px)`;
      line.hidden = !(x >= 0 && x <= u.over.clientWidth);
    };

    const u = new uPlot(
      {
        width: Math.max(160, element.clientWidth),
        height: HEIGHT,
        legend: { show: false },
        padding: [8, 8, 0, 0],
        scales: { x: { time: false, range } },
        cursor: { y: false, sync: { key: SYNC_KEY }, drag: { x: false, y: false }, points: { size: 8 } },
        axes: [
          {
            stroke: muted,
            font: FONT,
            size: 26,
            grid: { stroke: grid, width: 1 },
            ticks: { show: false },
            values: (_u, splits) => splits.map((v) => `${+v.toFixed(2)} s`),
          },
          { stroke: muted, font: FONT, size: 44, grid: { stroke: grid, width: 1 }, ticks: { show: false } },
        ],
        series: [
          {},
          ...spec.series.map((s) => ({
            label: s.label,
            stroke: s.slot ? token(`--series-${s.slot}`) : token("--text-secondary"),
            width: 2,
            dash: s.dash ? [...s.dash] : undefined,
            points: { show: false },
          })),
        ],
        hooks: {
          setCursor: [
            (u) => {
              const left = u.cursor.left ?? -1;
              hovering = left >= 0;
              show(hovering ? u.posToVal(left, "x") : playhead.t);
            },
          ],
          draw: [place],
        },
      },
      data as uPlot.AlignedData,
      element,
    );
    u.over.appendChild(line);
    place(u);
    show(playhead.t);
    const seek = (event: MouseEvent) => {
      const left = event.clientX - u.over.getBoundingClientRect().left; // the cursor may lag a frame
      if (left >= 0 && left <= u.over.clientWidth) playhead.seek(u.posToVal(left, "x"));
    };
    u.over.addEventListener("click", seek);
    const stop = playhead.subscribe(() => {
      place(u);
      if (!hovering) show(playhead.t);
    });
    const observer = new ResizeObserver(() => {
      const width = Math.max(160, element.clientWidth);
      if (width !== u.width) u.setSize({ width, height: HEIGHT });
    });
    observer.observe(element);
    return () => {
      stop();
      observer.disconnect();
      u.over.removeEventListener("click", seek);
      u.destroy();
    };
  }, [data, spec, range, playhead, theme, digits]);

  const many = spec.series.length > 1;
  return (
    <figure className="plot" data-testid={`plot-${spec.id}`}>
      <figcaption>
        <span className="plot-title">{spec.title}</span> <span className="muted">({spec.unit})</span>
        {!many && <b className="num plot-value" ref={(el) => void (values.current[0] = el)} />}
        <span className="spacer" />
        <span className="muted small num" ref={at} />
      </figcaption>
      {many && (
        <div className="plot-legend">
          {spec.series.map((s, i) => (
            <span className="plot-key" key={`${s.run}${s.column}`}>
              <LineSwatch series={s} />
              <span className="plot-label" title={s.label}>
                {s.label}
              </span>
              <b className="num" ref={(el) => void (values.current[i] = el)} />
            </span>
          ))}
        </div>
      )}
      <div className="plot-canvas" ref={box} title="Click to go to that moment" />
    </figure>
  );
}
