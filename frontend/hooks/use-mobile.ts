import * as React from "react";

const MOBILE_BREAKPOINT = 768;

// This file intentionally diverges from shadcn's generated output: the
// generated version derives `isMobile` with useState + an effect that calls
// setState synchronously in its body, which fails this repo's
// `react-hooks/set-state-in-effect` lint rule (.claude/rules/forms.md §6) and
// also returns `false` on the first render regardless of viewport (the
// `useState<boolean | undefined>(undefined)` starts undefined, coerced to
// false), so a phone briefly renders the desktop sidebar layout before
// correcting. useSyncExternalStore subscribes to the matchMedia list without
// an effect+setState and reads the true value on the very first render.
// If `shadcn add sidebar` regenerates this file, this fix is silently lost —
// notice it in review and reapply it.
function subscribe(callback: () => void) {
  const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`);
  mql.addEventListener("change", callback);
  return () => mql.removeEventListener("change", callback);
}

function getSnapshot() {
  return window.innerWidth < MOBILE_BREAKPOINT;
}

// The server has no viewport; `false` matches the previous behaviour's
// first-paint value and Next.js re-renders with the real value on hydration.
function getServerSnapshot() {
  return false;
}

export function useIsMobile(): boolean {
  return React.useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
