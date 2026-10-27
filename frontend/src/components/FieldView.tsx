import { useEffect, useRef, useState } from "react";
import type { Layers, Picture } from "../draw";
import { draw } from "../draw";
import type { Palette } from "../palette";
import { readPalette } from "../palette";
import type { SessionStore } from "../session";
import { onThemeChange } from "../theme";
import { Trail } from "../trail";
import type { View } from "../view";
import { fitView, pan, resize, toField, zoomAt } from "../view";

const EMPTY: Picture = { scene: null, frame: null, overlay: null, truth: new Trail(), estimate: new Trail() };

/** The field and the run on it, drawn every animation frame. Wheel: zoom; drag: pan;
 * double-click: the whole field again. */
export function FieldView(props: { store: SessionStore | null; layers: Layers }) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const cursor = useRef<HTMLDivElement>(null);
  const live = useRef(props);
  live.current = props;

  useEffect(() => {
    const element = canvas.current!;
    const container = box.current!;
    const ctx = element.getContext("2d");
    if (!ctx) return;
    let view: View | null = null;
    let fittedTo = "";
    let adjusted = false; // zoomed or panned by hand: keep that view on resize
    let colors: Palette = readPalette();
    let frameId = 0;
    let drag: { x: number; y: number; id: number } | null = null;

    const fieldSize = (): [number, number] => live.current.store?.scene?.field.size ?? [144, 144];
    const fit = () => {
      const [w, h] = fieldSize();
      view = fitView(w, h, container.clientWidth, container.clientHeight);
      fittedTo = `${w}x${h}`;
      adjusted = false;
    };

    const sizeCanvas = () => {
      const dpr = window.devicePixelRatio || 1;
      const width = container.clientWidth;
      const height = container.clientHeight;
      element.width = Math.max(1, Math.round(width * dpr));
      element.height = Math.max(1, Math.round(height * dpr));
      element.style.width = `${width}px`;
      element.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (view && adjusted) view = resize(view, width, height);
      else fit();
    };

    const render = () => {
      frameId = requestAnimationFrame(render);
      const { store, layers } = live.current;
      const [w, h] = fieldSize();
      if (!view || (fittedTo !== `${w}x${h}` && !adjusted)) fit();
      const picture: Picture = store
        ? { scene: store.scene, frame: store.frame, overlay: store.overlay, truth: store.truth, estimate: store.estimate }
        : EMPTY;
      draw(ctx, view!, colors, picture, layers);
      element.dataset.frames = String(store?.frames ?? 0);
    };

    const observer = new ResizeObserver(sizeCanvas);
    observer.observe(container);
    sizeCanvas();
    render();
    const stopTheme = onThemeChange(() => {
      colors = readPalette();
    });

    const local = (event: PointerEvent | WheelEvent | MouseEvent): [number, number] => {
      const rect = element.getBoundingClientRect();
      return [event.clientX - rect.left, event.clientY - rect.top];
    };
    const onWheel = (event: WheelEvent) => {
      if (!view) return;
      event.preventDefault();
      const [px, py] = local(event);
      view = zoomAt(view, px, py, Math.exp(-event.deltaY * 0.0015));
      adjusted = true;
    };
    const onDown = (event: PointerEvent) => {
      drag = { x: event.clientX, y: event.clientY, id: event.pointerId };
      element.setPointerCapture(event.pointerId);
    };
    const onMove = (event: PointerEvent) => {
      if (view && drag && drag.id === event.pointerId) {
        view = pan(view, event.clientX - drag.x, event.clientY - drag.y);
        drag = { ...drag, x: event.clientX, y: event.clientY };
        adjusted = true;
      }
      if (view && cursor.current) {
        const [x, y] = toField(view, ...local(event));
        cursor.current.textContent = `x ${x.toFixed(1)}  y ${y.toFixed(1)} in`;
      }
    };
    const onUp = (event: PointerEvent) => {
      if (drag && drag.id === event.pointerId) drag = null;
    };
    const onLeave = () => {
      if (cursor.current) cursor.current.textContent = "";
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    element.addEventListener("pointerdown", onDown);
    element.addEventListener("pointermove", onMove);
    element.addEventListener("pointerup", onUp);
    element.addEventListener("pointercancel", onUp);
    element.addEventListener("pointerleave", onLeave);
    element.addEventListener("dblclick", fit);
    return () => {
      cancelAnimationFrame(frameId);
      observer.disconnect();
      stopTheme();
      element.removeEventListener("wheel", onWheel);
      element.removeEventListener("pointerdown", onDown);
      element.removeEventListener("pointermove", onMove);
      element.removeEventListener("pointerup", onUp);
      element.removeEventListener("pointercancel", onUp);
      element.removeEventListener("pointerleave", onLeave);
      element.removeEventListener("dblclick", fit);
    };
  }, []);

  const empty = !props.store?.scene;
  return (
    <div className="fieldview" ref={box}>
      <canvas ref={canvas} data-testid="field" aria-label="The field, seen from above" role="img" />
      <div className="cursor" ref={cursor} aria-hidden="true" />
      {empty && (
        <div className="empty">
          <span>
            {props.store ? (
              props.store.state === "building" ? (
                "Building the project…"
              ) : props.store.state === "error" ? (
                "The run couldn't start: see the console below."
              ) : (
                "Starting…"
              )
            ) : (
              <>
                Pick a robot and a program, then press <b>Run</b>.
              </>
            )}
          </span>
        </div>
      )}
    </div>
  );
}

/** What the marks on the field mean, with switches for the ones that can be hidden. It sits
 * in the field's corner, beside the field itself when the view is wider than tall. */
export function FieldKey(props: { layers: Layers; onLayers: (layers: Layers) => void }) {
  const { layers } = props;
  const [open, setOpen] = useState(true);
  const row = (swatch: string, text: string, layer?: keyof Layers, title?: string) =>
    layer ? (
      <label className="keyrow" title={title}>
        <input type="checkbox" checked={layers[layer]} onChange={() => props.onLayers({ ...layers, [layer]: !layers[layer] })} />
        <i className={`swatch ${swatch}`} />
        {text}
      </label>
    ) : (
      <div className="keyrow">
        <span />
        <i className={`swatch ${swatch}`} />
        {text}
      </div>
    );
  return (
    <div className="fieldkey" role="group" aria-label="Key">
      <button type="button" className="keyhead" aria-expanded={open} onClick={() => setOpen(!open)}>
        Key <span aria-hidden="true">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <>
          {row("robot", "Robot (front edge thicker)")}
          {row("line truth", "Where it went", "trails", "Show the paths (T)")}
          {row("line dashed estimate", "Where its code thinks it is", "estimate", "Show the robot code's estimate (G)")}
          {row("line dashed target", "Motion path / target")}
          {row("line beam", "Distance beams", "beams", "Show distance sensor beams (B)")}
          {row("slip", "Wheel grip used")}
        </>
      )}
    </div>
  );
}
