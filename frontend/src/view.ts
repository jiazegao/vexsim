// Field inches <-> canvas pixels. The field's origin is its center, +x right, +y up;
// the canvas's y grows downward. `cx`, `cy` is the field point at the canvas center.

export interface View {
  scale: number; // pixels per inch
  cx: number;
  cy: number;
  width: number; // canvas size, CSS pixels
  height: number;
}

export const MIN_SCALE = 0.5;
export const MAX_SCALE = 60;

/** The whole field, centered, with `margin` pixels to spare. */
export function fitView(fieldWidth: number, fieldHeight: number, width: number, height: number, margin = 24): View {
  const usable = Math.max(1, Math.min(width - 2 * margin, height - 2 * margin));
  const scale = clamp(usable / Math.max(fieldWidth, fieldHeight, 1), MIN_SCALE, MAX_SCALE);
  return { scale, cx: 0, cy: 0, width, height };
}

export function toScreen(view: View, x: number, y: number): [number, number] {
  return [view.width / 2 + (x - view.cx) * view.scale, view.height / 2 - (y - view.cy) * view.scale];
}

export function toField(view: View, px: number, py: number): [number, number] {
  return [view.cx + (px - view.width / 2) / view.scale, view.cy - (py - view.height / 2) / view.scale];
}

/** Zoom by `factor`, keeping the field point under (px, py) where it is. */
export function zoomAt(view: View, px: number, py: number, factor: number): View {
  const scale = clamp(view.scale * factor, MIN_SCALE, MAX_SCALE);
  const [fx, fy] = toField(view, px, py);
  return {
    ...view,
    scale,
    cx: fx - (px - view.width / 2) / scale,
    cy: fy + (py - view.height / 2) / scale,
  };
}

/** Move the view with the pointer: dragging right shows what's to the left. */
export function pan(view: View, dx: number, dy: number): View {
  return { ...view, cx: view.cx - dx / view.scale, cy: view.cy + dy / view.scale };
}

/** The same view on a canvas of a new size (the field stays centered where it was). */
export function resize(view: View, width: number, height: number): View {
  return { ...view, width, height };
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}
