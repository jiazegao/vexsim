import type { HTMLAttributes } from "react";
import { useScrollFocus } from "../scrollfocus";

/** A <pre> that may scroll (code, a log): it takes a stop for Tab while what's in it doesn't
 * fit, so the arrow keys can scroll it (scrollfocus.ts). `label` says what it holds. */
export function ScrollPre(props: HTMLAttributes<HTMLPreElement> & { label: string }) {
  const { label, ...rest } = props;
  const ref = useScrollFocus<HTMLPreElement>();
  return <pre {...rest} ref={ref} role="group" aria-label={label} />;
}
