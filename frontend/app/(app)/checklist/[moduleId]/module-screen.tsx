"use client";

import {
  ClipboardCheck,
  Download,
  Eraser,
  MessagesSquare,
  Plus,
  Sparkles,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { toast } from "sonner";

import { ChangeSetPanel } from "@/components/checklist/change-set-panel";
import { CreateItemDialog } from "@/components/checklist/create-item-dialog";
import { ConfirmDialog } from "@/components/form/confirm-dialog";
import { ChatPanel } from "@/components/checklist/chat-panel";
import { ItemFilters } from "@/components/checklist/item-filters";
import { ItemGrid } from "@/components/checklist/item-grid";
import { ChecklistModuleStatusBadge } from "@/components/checklist/module-status-badge";
import { RefinementDrawer } from "@/components/checklist/refinement-drawer";
import { StalenessBadge } from "@/components/checklist/staleness-badge";
import { DetailError } from "@/components/feedback/detail-error";
import { JobFailureAlert } from "@/components/feedback/job-failure-alert";
import { ListError } from "@/components/feedback/list-error";
import { NotFound } from "@/components/feedback/not-found";
import { useBreadcrumbLabel } from "@/components/layout/breadcrumb-labels";
import { PageHeader } from "@/components/layout/page-header";
import { GenerateMockDataControl } from "@/components/mock-data/generate-control";
import { MockDataChangeSetPanel } from "@/components/mock-data/change-set-panel";
import { MockDataChatPanel } from "@/components/mock-data/chat-panel";
import { RecordsTable } from "@/components/mock-data/records-table";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useGenerateChecklistModule } from "@/hooks/use-checklist-mutations";
import { useChecklistModule, useModuleChangeSets } from "@/hooks/use-checklist";
import { useClearChecklistResults } from "@/hooks/use-checklist-mutations";
import { useMockDataChangeSets, useMockDataDataset } from "@/hooks/use-mock-data";
import { useProject } from "@/hooks/use-projects";
import { checklistItemListQueryString, endpoints } from "@/lib/api/endpoints";
import { useErrorText } from "@/lib/i18n/error-text";
import type { ChecklistItemListParams } from "@/lib/api/types";
import { PERMISSION, can } from "@/lib/can";

export function ModuleScreen({ moduleId }: { moduleId: string }) {
  const t = useTranslations("checklist.moduleScreen");
  const tCommon = useTranslations("common");
  const errorText = useErrorText();
  const query = useChecklistModule(moduleId);
  const generate = useGenerateChecklistModule(moduleId);
  const [filters, setFilters] = useState<Partial<ChecklistItemListParams>>({});
  const [addingItem, setAddingItem] = useState(false);
  const [confirmingClear, setConfirmingClear] = useState(false);
  const clearResults = useClearChecklistResults(moduleId);

  const checklistModule = query.data;
  useBreadcrumbLabel(`/checklist/${moduleId}`, checklistModule?.name);
  // Mirrors the backend gate; it does not replace it. A 403 still surfaces as an
  // error. Every permission check on this screen -- checklist and mock data alike --
  // reads off this one fetch, since both tabs belong to the same project.
  const project = useProject(checklistModule?.projectId ?? "");
  // Three states, not two: `null` is "not known yet" (loading, or the request
  // failed). It disables a control but never explains itself as a missing permission
  // -- only a loaded project can say that (§U8.14).
  const canGenerate = project.data ? can(project.data, PERMISSION.GENERATE_RUN) : null;
  const canApplyChangeSet = project.data
    ? can(project.data, PERMISSION.CHANGESET_APPLY)
    : false;
  const canEditMockData = project.data
    ? can(project.data, PERMISSION.MOCKDATA_EDIT)
    : null;
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
      ? t("mockDataGenerationRunning")
      : mockDataPendingChangeSetId
        ? t("applyOrDiscardFirst")
        : canEditMockData === false
          ? t("noMockDataPermission")
          : null;
  const mockDataGenerateDisabled =
    mockDataGenerateBlockedBecause !== null || canEditMockData !== true;

  if (query.isLoading) {
    return (
      <div className="mx-auto w-full max-w-7xl space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (query.error) {
    return (
      <DetailError
        error={query.error}
        notFoundMessage={t("notFound")}
        onRetry={() => query.refetch()}
      />
    );
  }

  if (!checklistModule) return <NotFound />;

  const isGenerating = checklistModule.status === "generating";
  const generateBlockedBecause = isGenerating
    ? t("generationRunning")
    : pendingChangeSetId
      ? t("applyOrDiscardFirst")
      : canGenerate === false
        ? t("noGeneratePermission")
        : null;
  const generateDisabled = generateBlockedBecause !== null || canGenerate !== true;

  return (
    <div className="mx-auto w-full max-w-7xl space-y-6">
      {/* The project carries the caller's permissions. If it failed, say so rather
          than leaving every gated control to claim a missing permission (§U8.14). */}
      {project.isError ? (
        <ListError error={project.error} onRetry={() => project.refetch()} />
      ) : null}

      <Tabs defaultValue="checklist">
        <TabsList>
          <TabsTrigger value="checklist">{t("tabs.testPlan")}</TabsTrigger>
          <TabsTrigger value="mock-data">{t("tabs.mockData")}</TabsTrigger>
        </TabsList>

        <TabsContent value="checklist" className="space-y-6">
          <PageHeader
            title={checklistModule.name}
            titleAddon={
              <>
                <ChecklistModuleStatusBadge status={checklistModule.status} />
                {checklistModule.stale ? <StalenessBadge /> : null}
              </>
            }
            // The scope of the checklist, stated rather than implied. A test plan
            // built from one path is not coverage of the application, and a reader
            // who cannot see which path was enumerated has no way to notice what
            // was never in scope (spec 4.6). This is also why nothing on this
            // screen shows a percentage or a "complete" badge -- there is no such
            // claim to make.
            description={t.rich("description", {
              sourcePath: checklistModule.sourcePath,
              appName: tCommon("appName"),
              path: (chunks) => <span className="font-mono">{chunks}</span>,
            })}
            action={
              <div className="flex items-center gap-2">
                {generateBlockedBecause ? (
                  <Tooltip>
                    <TooltipTrigger
                      render={
                        <span>
                          <Button disabled>
                            <Sparkles className="size-4" />
                            {t("generate")}
                          </Button>
                        </span>
                      }
                    />
                    <TooltipContent>{generateBlockedBecause}</TooltipContent>
                  </Tooltip>
                ) : (
                  <Button
                    disabled={generate.isPending || generateDisabled}
                    onClick={() =>
                      generate.mutate(undefined, {
                        onSuccess: () => toast.success(t("generationStarted")),
                        onError: (error) => toast.error(errorText(error)),
                      })
                    }
                  >
                    <Sparkles className="size-4" />
                    {t("generate")}
                  </Button>
                )}

                {pendingChangeSet ? (
                  <RefinementDrawer
                    label={t("reviewChanges", {
                      count: pendingChangeSet.operations.length,
                    })}
                    icon={ClipboardCheck}
                    variant="default"
                    title={t("pendingChanges")}
                    description={t("pendingChecklistDescription")}
                    storageKey="checklist-review"
                  >
                    <ChangeSetPanel
                      key={pendingChangeSet.id}
                      changeSet={pendingChangeSet}
                      moduleId={moduleId}
                      items={checklistModule.items}
                      canApply={canApplyChangeSet}
                    />
                  </RefinementDrawer>
                ) : pendingChangeSetId && changeSets.isLoading ? (
                  // The tooltip above already points at this button; hold its place
                  // until the list arrives (a failure is the inline error below).
                  <Skeleton className="h-9 w-36" />
                ) : null}

                <RefinementDrawer
                  label={t("refine")}
                  icon={MessagesSquare}
                  title={t("refineChecklistTitle")}
                  description={t("refineChecklistDescription")}
                  storageKey="checklist-refine"
                >
                  <ChatPanel
                    moduleId={moduleId}
                    hasPendingChangeSet={pendingChangeSetId !== null}
                    isGenerating={isGenerating}
                    canSend={canGenerate}
                  />
                </RefinementDrawer>

                <Button variant="outline" onClick={() => setAddingItem(true)}>
                  <Plus className="size-4" />
                  {t("addTestCase")}
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
                  {t("export")}
                </Button>
              </div>
            }
          />

          {pendingChangeSetId && changeSets.isError ? (
            <ListError error={changeSets.error} onRetry={() => changeSets.refetch()} />
          ) : null}

          {checklistModule.status === "failed" && checklistModule.error ? (
            <JobFailureAlert
              title={t("lastGenerationFailed")}
              message={checklistModule.error}
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
                {t("clearResults", { count: recordedCount })}
              </Button>
            </div>
          ) : null}

          <ItemGrid items={items} moduleId={moduleId} isGenerating={isGenerating} />

          <ConfirmDialog
            open={confirmingClear}
            onOpenChange={setConfirmingClear}
            title={t("clearTitle")}
            description={t("clearDescription", { count: recordedCount })}
            confirmLabel={t("clearConfirm")}
            isPending={clearResults.isPending}
            error={clearResults.error}
            onConfirm={() =>
              clearResults.mutate(filters, {
                onSuccess: (data) => {
                  toast.success(t("cleared", { count: data.clearedCount }));
                  setConfirmingClear(false);
                },
                onError: (error) => toast.error(errorText(error)),
              })
            }
          />

          <CreateItemDialog
            moduleId={moduleId}
            open={addingItem}
            onOpenChange={setAddingItem}
          />
        </TabsContent>

        <TabsContent value="mock-data" className="space-y-6">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold tracking-tight">
                {t("mockDataTitle")}
              </h2>
              <p className="text-muted-foreground text-sm">
                {t("mockDataDescription", { path: checklistModule.sourcePath })}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <GenerateMockDataControl
                moduleId={moduleId}
                blockedBecause={mockDataGenerateBlockedBecause}
                disabled={mockDataGenerateDisabled}
              />

              {pendingMockDataChangeSet ? (
                <RefinementDrawer
                  label={t("reviewChanges", {
                    count: pendingMockDataChangeSet.operations.length,
                  })}
                  icon={ClipboardCheck}
                  variant="default"
                  title={t("pendingChanges")}
                  description={t("pendingMockDataDescription")}
                  storageKey="mock-data-review"
                >
                  <MockDataChangeSetPanel
                    key={pendingMockDataChangeSet.id}
                    changeSet={pendingMockDataChangeSet}
                    moduleId={moduleId}
                    records={mockData.data?.records ?? []}
                    canApply={canEditMockData === true}
                  />
                </RefinementDrawer>
              ) : mockDataPendingChangeSetId && mockDataChangeSets.isLoading ? (
                <Skeleton className="h-9 w-36" />
              ) : null}

              <RefinementDrawer
                label={t("refine")}
                icon={MessagesSquare}
                title={t("refineMockDataTitle")}
                description={t("refineMockDataDescription")}
                storageKey="mock-data-refine"
              >
                <MockDataChatPanel
                  moduleId={moduleId}
                  hasPendingChangeSet={mockDataPendingChangeSetId !== null}
                  isGenerating={mockData.data?.status === "generating"}
                  canSend={canEditMockData}
                />
              </RefinementDrawer>
              <Button
                variant="outline"
                nativeButton={false}
                render={<a href={`/api${endpoints.mockData.exportJson(moduleId)}`} />}
              >
                <Download className="size-4" />
                {t("exportJson")}
              </Button>
              <Button
                variant="outline"
                nativeButton={false}
                render={<a href={`/api${endpoints.mockData.exportXlsx(moduleId)}`} />}
              >
                <Download className="size-4" />
                {t("exportXlsx")}
              </Button>
            </div>
          </div>

          {mockDataPendingChangeSetId && mockDataChangeSets.isError ? (
            <ListError
              error={mockDataChangeSets.error}
              onRetry={() => mockDataChangeSets.refetch()}
            />
          ) : null}

          {mockData.data?.status === "failed" && mockData.data.error ? (
            <JobFailureAlert
              title={t("lastGenerationFailed")}
              message={mockData.data.error}
            />
          ) : null}

          {/* The dataset is its own request, fetched from inside an already-rendered
              tab, so the screen-level gate above does not cover it. Without these two
              branches `RecordsTable` renders "No mock data yet -- generate a batch"
              while the fetch is still in flight, and keeps that invitation up
              permanently if it fails -- over a dataset that already exists
              (`docs/audit-finding-solved-logs.md` §U7.6). */}
          {mockData.isLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 5 }, (_, index) => (
                <Skeleton key={index} className="h-12 w-full" />
              ))}
            </div>
          ) : mockData.isError ? (
            <ListError error={mockData.error} onRetry={() => mockData.refetch()} />
          ) : (
            <RecordsTable
              moduleId={moduleId}
              records={mockData.data?.records ?? []}
              canEdit={canEditMockData === true}
              isGenerating={mockData.data?.status === "generating"}
            />
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
