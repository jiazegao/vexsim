import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { StepOption } from "../stepsearch";
import { marked, searchSteps } from "../stepsearch";

const LIST_MAX_PX = 320;

/** Where the list goes: under the box, or over it when there's more room there. Fixed to the
 * window, so the panel the box is in doesn't cut it off. */
interface Place {
  left: number;
  width: number;
  top?: number;
  bottom?: number;
  maxHeight: number;
}

/** "Add a step": a box to type in, and the steps that match what's typed in a list under it
 * (all of them, empty), best first. ↑/↓ and Enter, or a click, pick one; Esc closes the list,
 * then empties the box. */
export function StepPicker(props: { options: readonly StepOption[]; onPick: (option: StepOption) => void }) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [place, setPlace] = useState<Place | null>(null);
  const box = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const id = useId();
  const shown = useMemo(() => searchSteps(props.options, query), [props.options, query]);

  const position = useCallback(() => {
    const rect = box.current?.getBoundingClientRect();
    if (!rect) return;
    const below = window.innerHeight - rect.bottom - 8;
    const above = rect.top - 8;
    const up = below < 200 && above > below;
    const room = Math.min(LIST_MAX_PX, up ? above : below);
    setPlace({ left: rect.left, width: rect.width, maxHeight: room, ...(up ? { bottom: window.innerHeight - rect.top + 2 } : { top: rect.bottom + 2 }) });
  }, []);
  useEffect(() => {
    if (!open) return;
    position();
    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, true); // the panel scrolling under it too
    return () => {
      window.removeEventListener("resize", position);
      window.removeEventListener("scroll", position, true);
    };
  }, [open, position]);
  useEffect(() => setActive(0), [query]);
  useEffect(() => {
    if (open) list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  const pick = (option: StepOption) => {
    setQuery("");
    setOpen(false);
    props.onPick(option);
  };
  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) setOpen(true);
      else setActive((at) => Math.min(Math.max(at + (event.key === "ArrowDown" ? 1 : -1), 0), Math.max(shown.length - 1, 0)));
    } else if (event.key === "Enter") {
      if (open && shown[active]) {
        event.preventDefault();
        pick(shown[active]);
      }
    } else if (event.key === "Escape") {
      if (!open && !query) return;
      event.preventDefault();
      event.stopPropagation();
      if (open) setOpen(false);
      else setQuery("");
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  };

  const listId = `${id}-steps`;
  return (
    <div className="step-picker">
      <input
        ref={box}
        className="route-add"
        role="combobox"
        aria-label="Add a step"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && shown[active] ? `${id}-${active}` : undefined}
        placeholder="Add a step: type to find a motion, a pause or a function…"
        value={query}
        onChange={(e) => {
          setQuery(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={() => setOpen(true)}
        onKeyDown={onKeyDown}
        data-testid="add-step"
      />
      {open && place && (
        <ul ref={list} id={listId} role="listbox" aria-label="Steps to add" className="step-picker-list" style={{ position: "fixed", ...place }} data-testid="add-step-list">
          {shown.length === 0 && <li className="step-picker-none muted small">Nothing matches “{query.trim()}”</li>}
          {shown.map((option, i) => {
            const [before, match, after] = marked(option.title, query);
            return (
              <li
                key={option.id}
                id={`${id}-${i}`}
                role="option"
                aria-selected={i === active}
                className={i === active ? "on" : undefined}
                title={option.header ? `${option.detail}\nIn ${option.header}: picking it adds the header to the route's functions` : option.detail}
                onMouseDown={(e) => e.preventDefault()} // the box keeps the focus
                onMouseMove={() => i !== active && setActive(i)}
                onClick={() => pick(option)}
                data-testid={`add-step-option-${option.id}`}
              >
                <span className="step-picker-title">
                  {before}
                  {match && <mark>{match}</mark>}
                  {after}
                </span>
                <span className="step-picker-group">{option.header ? `${option.group} (adds it)` : option.group}</span>
                <span className="step-picker-detail">{option.detail}</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
