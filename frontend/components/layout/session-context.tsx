"use client";

import { createContext, useContext } from "react";

import type { UserResponse } from "@/lib/api/types";

const SessionContext = createContext<UserResponse | null>(null);

export function SessionProvider({
  user,
  children,
}: {
  user: UserResponse;
  children: React.ReactNode;
}) {
  return <SessionContext.Provider value={user}>{children}</SessionContext.Provider>;
}

/** The current operator. Resolved before the first byte, so it is never null here. */
export function useSessionUser(): UserResponse {
  const user = useContext(SessionContext);
  if (!user) throw new Error("useSessionUser must be used inside the app shell");
  return user;
}
