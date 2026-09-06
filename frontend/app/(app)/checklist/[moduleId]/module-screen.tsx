"use client";

import { Download, Eraser, Plus, Sparkles } from "lucide-react";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { ChangeSetPanel } from "@/components/checklist/change-set-panel";
import { CreateItemDialog } from "@/components/checklist/create-item-dialog";
import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { ChatPanel } from "@/components/checklist/chat-panel";
import { ItemFilters } from "@/components/checklist/item-filters";
import { ItemGrid } from "@/components/checklist/item-grid";
import { ChecklistModuleStatusBadge } from "@/components/checklist/module-status-badge";
import { StalenessBadge } from "@/components/checklist/staleness-badge";
import { NotFound } from "@/components/feedback/not-found";
import { GenerateMockDataControl } from "@/components/mock-data/generate-control";
import { MockDataChangeSetPanel } from "@/components/mock-data/change-set-panel";
import { MockDataChatPanel } from "@/components/mock-data/chat-panel";
import { RecordsTable } from "@/components/mock-data/records-table";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useGenerateChecklistModule } from "@/hooks/use-checklist-mutations";
import { useSession } from "@/hooks/use-session";
import { useChecklistModule, useModuleChangeSets } from "@/hooks/use-checklist";
import { useClearChecklistResults } from "@/hooks/use-checklist-mutations";
import { useMockDataChangeSets, useMockDataDataset } from "@/hooks/use-mock-data";
import { checklistItemListQueryString, endpoints } from "@/lib/api/endpoints";
import { isApiError } from "@/lib/api/errors";
import type { ChecklistItemListParams } from "@/lib/api/types";

export function ModuleScreen({ moduleId }: { moduleId: string }) {
  const user = useSession();
  const query = useChecklistModule(moduleId);
  const generate = useGenerateChecklistModule(moduleId);
  const [filters, setFilters] = useState<Partial<ChecklistItemListParams>>({});
  const [addingItem, setAddingItem] = useState(false);
  const [confirmingClear, setConfirmingClear] = useState(false);
  const clearResults = useClearChecklistResults(moduleId);

  const checklistModule = query.data;
  const pendingChangeSetId = checklistModule?.pendingChangeSetId ?? null;
  // Only fetched when there is something to review: the audit trail is not on screen
  // otherwise, and a module in `ready` should not pay for the request.
  const changeSets = useModuleChangeSets(moduleId, pendingChangeSetId !== null);
  const pendingChangeSet = useMemo(
    () =>
      changeSets.data?.find((candidate) => candidate.id === pendingChangeSetId) ?? null,
    [changeSets.data, pendingChangeSetId],
  );

  const items = useMemo(() => {
    const all = checklistModule?.items ?? [];
    // Filtered client-side: the detail response already carries every item in the
    // module, so a second request per filter change would fetch what we hold.
    return all.filter(
      (item) =>
        (!filters.feature ||
          item.feature.toLowerCase().includes(filters.feature.toLowerCase())) &&
        (!filters.status || item.status === filters.status) &&
        (!filters.source || item.source === filters.source) &&
        (!filters.kind || item.kind === filters.kind),
    );
  }, [checklistModule?.items, filters]);

  // Counted from the rows on screen so the button can name the number, and hidden
  // entirely at zero -- an enabled control that would do nothing is worse than none.
  const recordedCount = items.filter((item) => item.status !== "untested").length;

  const mockData = useMockDataDataset(moduleId);
  const mockDataPendingChangeSetId = mockData.data?.pendingChangeSetId ?? null;
  const mockDataChangeSets = useMockDataChangeSets(
    moduleId,
    mockDataPendingChangeSetId !== null,
  );
  const pendingMockDataChangeSet = useMemo(
    () =>
      mockDataChangeSets.data?.find(
        (candidate) => candidate.id === mockDataPendingChangeSetId,
      ) ?? null,
    [mockDataChangeSets.data, mockDataPendingChangeSetId],
  );
  const mockDataGenerateBlockedBecause =
    mockData.data?.status === "generating"
      ? "A generation is already running for this dataset."
      : mockDataPendingChangeSetId
        ? "Apply or discard the pending changes before generating again."
        : null;

  if (query.isLoading) {
    return (
      <div className="mx-auto w-full max-w-7xl space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (query.error) {
    // Module existence is deliberately public, so a miss is only ever a 404.
    if (isApiError(query.error) && query.error.status === 404) {
      return (
        <NotFound message="That checklist module does not exist, or it was deleted." />
      );
    }
    return <NotFound message={(query.error as Error).message} />;
  }

  if (!checklistModule) return <NotFound />;

  const isGenerating = checklistModule.status === "generating";
  const generateBlockedBecause = isGenerating
    ? "A generation is already running for this module."
    : pendingChangeSetId
      ? "Apply or discard the pending changes before generating again."
      : null;

  return (
    <div className="mx-auto w-full max-w-7xl space-y-6">
      <Tabs defaultValue="checklist">
        <TabsList>
          <TabsTrigger value="checklist">Test Plan</TabsTrigger>
          <TabsTrigger value="mock-data">Mock Data</TabsTrigger>
        </TabsList>

        <TabsContent value="checklist" className="space-y-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex flex-wrap items-center gap-3">
                <h1 className="text-3xl font-semibold tracking-tight">
                  {checklistModule.name}
                </h1>
                <ChecklistModuleStatusBadge status={checklistModule.status} />
                {checklistModule.stale ? <StalenessBadge /> : null}
              </div>
              {/*
                The scope of the checklist, stated rather than implied. A test plan built
                from one path is not coverage of the application, and a reader who cannot
                see which path was enumerated has no way to notice what was never in scope
                (spec 4.6). This is also why nothing on this screen shows a percentage or a
                "complete" badge -- there is no such claim to make.
              */}
              <p className="text-muted-foreground mt-1 text-base">
                Enumerated from{" "}
                <span className="font-mono">{checklistModule.sourcePath}</span>. Only
                files AskRepo indexed are covered.
              </p>
            </div>

            <div className="flex items-center gap-2">
              {generateBlockedBecause ? (
                <Tooltip>
                  <TooltipTrigger
                    render={
                      <span>
                        <Button disabled>
                          <Sparkles className="size-4" />
                          Generate
                        </Button>
                      </span>
                    }
                  />
                  <TooltipContent>{generateBlockedBecause}</TooltipContent>
                </Tooltip>
              ) : (
                <Button
                  disabled={generate.isPending}
                  onClick={() =>
                    generate.mutate(undefined, {
                      onSuccess: () =>
                        toast.success(
                          "Generating. The proposals appear here when it finishes.",
                        ),
                      onError: (error) =>
                        toast.error(
                          isApiError(error)
                            ? error.message
                            : "That did not start. Try again.",
                        ),
                    })
                  }
                >
                  <Sparkles className="size-4" />
                  Generate
                </Button>
              )}

              <Button variant="outline" onClick={() => setAddingItem(true)}>
                <Plus className="size-4" />
                Add test case
              </Button>

              <Button
                variant="outline"
                nativeButton={false}
                render={
                  <a
                    href={`/api/checklist-items/export${checklistItemListQueryString({
                      ...filters,
                      moduleId,
                    })}`}
                  />
                }
              >
                <Download className="size-4" />
                Export
              </Button>
            </div>
          </div>

          {checklistModule.status === "failed" && checklistModule.error ? (
            <Alert variant="destructive">
              <AlertTitle>The last generation failed</AlertTitle>
              <AlertDescription>{checklistModule.error}</AlertDescription>
            </Alert>
          ) : null}

          {pendingChangeSet ? (
            <ChangeSetPanel
              changeSet={pendingChangeSet}
              moduleId={moduleId}
              items={checklistModule.items}
            />
          ) : null}

          <ItemFilters currentFilters={filters} onFiltersChange={setFilters} />

          {recordedCount > 0 ? (
            <div className="flex justify-end">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setConfirmingClear(true)}
                disabled={clearResults.isPending}
              >
                <Eraser className="size-4" />
                Clear {recordedCount} recorded{" "}
                {recordedCount === 1 ? "result" : "results"}
              </Button>
            </div>
          ) : null}

          <ItemGrid items={items} moduleId={moduleId} user={user} />

          <ConfirmDialog
            open={confirmingClear}
            onOpenChange={setConfirmingClear}
            title="Clear these recorded results?"
            description={`This resets ${recordedCount} ${recordedCount === 1 ? "result" : "results"} to untested and discards what was observed. Only the rows the current filter selects are affected. The test cases stay.`}
            confirmLabel="Clear results"
            isPending={clearResults.isPending}
            error={clearResults.error}
            onConfirm={() =>
              clearResults.mutate(filters, {
                onSuccess: (data) => {
                  toast.success(
                    `Cleared ${data.clearedCount} recorded ${data.clearedCount === 1 ? "result" : "results"}`,
                  );
                  setConfirmingClear(false);
                },
                onError: (error) =>
                  toast.error(
                    isApiError(error)
                      ? error.message
                      : "That did not clear. Try again.",
                  ),
              })
            }
          />

          <CreateItemDialog
            moduleId={moduleId}
            open={addingItem}
            onOpenChange={setAddingItem}
          />

          <ChatPanel
            moduleId={moduleId}
            hasPendingChangeSet={pendingChangeSetId !== null}
          />
        </TabsContent>

        <TabsContent value="mock-data" className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold tracking-tight">Mock data</h2>
              <p className="text-muted-foreground text-sm">
                Sample records for {checklistModule.sourcePath}, grounded in its actual
                schema.
              </p>
            </div>
            <div className="flex items-center gap-2">
              <GenerateMockDataControl
                moduleId={moduleId}
                blockedBecause={mockDataGenerateBlockedBecause}
              />
              <Button
                variant="outline"
                nativeButton={false}
                render={<a href={`/api${endpoints.mockData.exportJson(moduleId)}`} />}
              >
                <Download className="size-4" />
                JSON
              </Button>
              <Button
                variant="outline"
                nativeButton={false}
                render={<a href={`/api${endpoints.mockData.exportXlsx(moduleId)}`} />}
              >
                <Download className="size-4" />
                xlsx
              </Button>
            </div>
          </div>

          {mockData.data?.status === "failed" && mockData.data.error ? (
            <Alert variant="destructive">
              <AlertTitle>The last generation failed</AlertTitle>
              <AlertDescription>{mockData.data.error}</AlertDescription>
            </Alert>
          ) : null}

          {pendingMockDataChangeSet ? (
            <MockDataChangeSetPanel
              changeSet={pendingMockDataChangeSet}
              moduleId={moduleId}
              records={mockData.data?.records ?? []}
            />
          ) : null}

          <RecordsTable moduleId={moduleId} records={mockData.data?.records ?? []} />

          <MockDataChatPanel
            moduleId={moduleId}
            hasPendingChangeSet={mockDataPendingChangeSetId !== null}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
