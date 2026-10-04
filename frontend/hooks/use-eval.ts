"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useLiveEvents } from "@/hooks/use-live-events";
import { apiFetch } from "@/lib/api/client";
import { endpoints } from "@/lib/api/endpoints";
import type {
  EvalPair,
  EvalRunDetail,
  EvalRunSummary,
  EvalSetCreateInput,
  EvalSetDetail,
  EvalSetSummary,
  PaginatedResponse,
} from "@/lib/api/types";
import { keys } from "@/lib/query/keys";

/** The interval is a fallback for a lost live event; `connected` relaxes it to a minute. */
function pollWhile(live: boolean, connected: boolean): number | false {
  return live ? (connected ? 60_000 : 3000) : false;
}

/** A project's eval sets, newest first. Polls while any set is still generating. */
export function useEvalSets(projectId: string) {
  const { connected } = useLiveEvents();
  return useQuery({
    queryKey: keys.eval.sets(projectId),
    queryFn: () =>
      apiFetch<PaginatedResponse<EvalSetSummary>>(
        `${endpoints.eval.projectSets(projectId)}?limit=100`,
      ),
    enabled: Boolean(projectId),
    refetchInterval: (query) =>
      pollWhile(
        (query.state.data?.items ?? []).some(
          (set) => set.status === "generating" || set.latestRun?.status === "running",
        ),
        connected,
      ),
    refetchIntervalInBackground: false,
  });
}

export function useEvalSet(setId: string) {
  const { connected } = useLiveEvents();
  return useQuery({
    queryKey: keys.eval.set(setId),
    queryFn: () => apiFetch<EvalSetDetail>(endpoints.eval.set(setId)),
    enabled: Boolean(setId),
    refetchInterval: (query) =>
      pollWhile(query.state.data?.status === "generating", connected),
    refetchIntervalInBackground: false,
  });
}

/** A set's runs, newest first. Polls while any run is still running. */
export function useEvalRuns(setId: string) {
  const { connected } = useLiveEvents();
  return useQuery({
    queryKey: keys.eval.runs(setId),
    queryFn: () =>
      apiFetch<PaginatedResponse<EvalRunSummary>>(
        `${endpoints.eval.setRuns(setId)}?limit=100`,
      ),
    enabled: Boolean(setId),
    refetchInterval: (query) =>
      pollWhile(
        (query.state.data?.items ?? []).some((run) => run.status === "running"),
        connected,
      ),
    refetchIntervalInBackground: false,
  });
}

export function useEvalRun(runId: string) {
  const { connected } = useLiveEvents();
  return useQuery({
    queryKey: keys.eval.run(runId),
    queryFn: () => apiFetch<EvalRunDetail>(endpoints.eval.run(runId)),
    enabled: Boolean(runId),
    refetchInterval: (query) =>
      pollWhile(query.state.data?.status === "running", connected),
    refetchIntervalInBackground: false,
  });
}

export function useGenerateEvalSet(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: EvalSetCreateInput) =>
      apiFetch<EvalSetSummary>(endpoints.eval.projectSets(projectId), {
        method: "POST",
        body: JSON.stringify(input),
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: keys.eval.sets(projectId) }),
  });
}

export function useStartEvalRun(setId: string, projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiFetch<EvalRunSummary>(endpoints.eval.setRuns(setId), { method: "POST" }),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: keys.eval.runs(setId) }),
        queryClient.invalidateQueries({ queryKey: keys.eval.sets(projectId) }),
      ]),
  });
}

export function useSetPairExcluded(setId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { pairId: string; excluded: boolean }) =>
      apiFetch<EvalPair>(endpoints.eval.pairExcluded(input.pairId), {
        method: "PUT",
        body: JSON.stringify({ excluded: input.excluded }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: keys.eval.set(setId) }),
  });
}

export function useDeleteEvalSet(projectId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (setId: string) =>
      apiFetch<void>(endpoints.eval.set(setId), { method: "DELETE" }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: keys.eval.sets(projectId) }),
  });
}
