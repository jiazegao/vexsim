import { useSyncExternalStore } from "react";
import type { SessionStore } from "./session";

const never = () => () => {};
const zero = () => 0;

/** Re-render when the session store changes (frames at most 10 times a second). */
export function useStore(store: SessionStore | null): number {
  return useSyncExternalStore(store ? store.subscribe : never, store ? store.getVersion : zero);
}
