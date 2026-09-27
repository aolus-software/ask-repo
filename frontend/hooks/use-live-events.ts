"use client";

import { createContext, useContext } from "react";

export interface LiveEventsState {
  connected: boolean;
}

/** Outside the provider — signed-out pages, tests — hooks see `connected: false` and poll. */
export const LiveEventsContext = createContext<LiveEventsState>({ connected: false });

export function useLiveEvents(): LiveEventsState {
  return useContext(LiveEventsContext);
}
