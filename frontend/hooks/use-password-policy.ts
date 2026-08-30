"use client";

import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type { PasswordPolicyResponse } from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

/**
 * The password rules, read from the backend rather than restated here.
 *
 * `.claude/rules/forms.md` §4 forbids copying a backend rule into the client, because
 * a copy drifts: an operator who raises `PASSWORD_MIN_LENGTH` would otherwise get a UI
 * still promising the old number. Rendering whatever this returns keeps one source of
 * truth while still showing the operator what is expected of them.
 *
 * The policy changes only when an operator edits settings and restarts, so it is
 * cached for the session rather than refetched per form.
 */
export function usePasswordPolicy() {
  return useQuery({
    queryKey: keys.passwordPolicy,
    queryFn: () => apiFetch<PasswordPolicyResponse>(endpoints.auth.passwordPolicy),
    staleTime: Infinity,
    gcTime: Infinity,
  });
}
