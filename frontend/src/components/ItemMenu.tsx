import { useEffect, useLayoutEffect, useRef, useState } from "react";

/** Something a menu does: a button (`run`, which can fail and say why) or a link (`href`, an
 * editor's vscode:// address). One with `disabled` says why it can't be done; one with
 * `confirm` asks that question first. */
export interface MenuAction {
  label: string;
  testid: string;
  title?: string;
  run?: () => unknown;
  href?: string;
  disabled?: string | null;
  confirm?: string;
}

/** A small menu at `at` (the pointer, or below the button that opened it), kept inside the
 * window: the arrow keys move through it, Escape or a click elsewhere closes it, and so does
 * an action once it's done. An action that fails leaves it open, saying why. */
export function ItemMenu(props: { label: string; at: { x: number; y: number }; actions: MenuAction[]; onClose: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  const [asking, setAsking] = useState<MenuAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [place, setPlace] = useState(props.at);
  const close = useRef(props.onClose); // the latest: listeners added once call it
  close.current = props.onClose;

  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return;
    const { width, height } = element.getBoundingClientRect();
    setPlace({
      x: Math.max(4, Math.min(props.at.x, window.innerWidth - width - 4)),
      y: Math.max(4, Math.min(props.at.y, window.innerHeight - height - 4)),
    });
  }, [props.at, asking, error]);

  useEffect(() => {
    const onClose = () => close.current();
    const away = (event: Event) => {
      const target = event.target as Element;
      if (box.current?.contains(target) || target.closest?.("[data-menu-trigger]")) return; // its button toggles it
      onClose();
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      onClose();
    };
    window.addEventListener("pointerdown", away, true);
    window.addEventListener("contextmenu", away, true);
    window.addEventListener("keydown", escape, true);
    window.addEventListener("resize", onClose);
    window.addEventListener("blur", onClose);
    return () => {
      window.removeEventListener("pointerdown", away, true);
      window.removeEventListener("contextmenu", away, true);
      window.removeEventListener("keydown", escape, true);
      window.removeEventListener("resize", onClose);
      window.removeEventListener("blur", onClose);
    };
  }, []);

  // the first thing it offers has the keyboard
  useEffect(() => {
    box.current?.querySelector<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])')?.focus();
  }, [asking]);

  const act = async (action: MenuAction) => {
    if (action.confirm && asking !== action) {
      setAsking(action);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await action.run?.();
      close.current();
    } catch (problem) {
      setError((problem as Error).message);
      setAsking(null);
    } finally {
      setBusy(false);
    }
  };
  const move = (event: React.KeyboardEvent) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const items = [...(box.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([aria-disabled="true"])') ?? [])];
    const at = items.indexOf(document.activeElement as HTMLElement);
    const next = event.key === "ArrowDown" ? at + 1 : at - 1;
    items[(next + items.length) % items.length]?.focus();
  };

  return (
    <div
      className="item-menu"
      role="menu"
      aria-label={props.label}
      ref={box}
      style={{ left: place.x, top: place.y }}
      onKeyDown={move}
      onContextMenu={(e) => e.preventDefault()}
      data-testid="item-menu"
    >
      {asking ? (
        <>
          <p className="item-menu-ask">{asking.confirm}</p>
          <button type="button" role="menuitem" className="danger" disabled={busy} onClick={() => act(asking)} data-testid={`${asking.testid}-confirm`}>
            {busy ? "…" : asking.label}
          </button>
          <button type="button" role="menuitem" onClick={() => setAsking(null)}>
            Cancel
          </button>
        </>
      ) : (
        props.actions.map((action) =>
          action.href && !action.disabled ? (
            // left in place until its link is followed: a link taken out of the page goes nowhere
            <a key={action.testid} role="menuitem" href={action.href} title={action.title} onClick={() => setTimeout(() => close.current())} data-testid={action.testid}>
              {action.label}
            </a>
          ) : (
            <button
              key={action.testid}
              type="button"
              role="menuitem"
              aria-disabled={action.disabled ? true : undefined}
              disabled={busy}
              title={action.disabled ?? action.title}
              onClick={() => !action.disabled && act(action)}
              data-testid={action.testid}
            >
              {action.label}
              {action.confirm ? "…" : ""}
            </button>
          ),
        )
      )}
      {error && (
        <p className="item-menu-error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
