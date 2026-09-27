const BASE_MS = 1000;
const CAP_MS = 60_000;
const JITTER = 0.2;

/**
 * Reconnect delay: one second doubling to a minute, ±20% so many tabs do not reconnect in
 * lockstep after an outage. `random` is injectable for tests.
 */
export function nextDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(CAP_MS, BASE_MS * 2 ** attempt);
  if (base === CAP_MS) return CAP_MS;
  return Math.round(base * (1 - JITTER + random() * 2 * JITTER));
}
