"use client";

import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { ListError } from "@/components/feedback/list-error";
import { ItemFilters } from "@/components/checklist/item-filters";
import { FormPage } from "@/components/form/form-page";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@/components/ui/combobox";
import {
  Field,
  FieldDescription,
  FieldError,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { useChecklistModules } from "@/hooks/use-checklist";
import { useProjectExport } from "@/hooks/use-checklist-mutations";
import { useProjects } from "@/hooks/use-projects";
import { SORT } from "@/lib/api/endpoints";
import type {
  ChecklistItemListParams,
  ProjectExportPart,
  ProjectResponse,
} from "@/lib/api/types";
import { PERMISSION, can } from "@/lib/can";

/** The project picker loads one page of this size; a longer list is cut off. */
const PROJECT_LIMIT = 100;

/** The list route's own page cap; a project past it can still export "All modules". */
const MODULE_LIMIT = 100;

type ModuleMode = "all" | "choose";

/**
 * Export a project's test checklist and/or mock data: every module, or a chosen set.
 *
 * A page rather than a dialog because it holds a checkbox picker and more than four
 * inputs (`.claude/rules/forms.md` §1). The project starts on `?projectId`, which the
 * Export button on `/checklist` passes from its own project filter.
 */
export function ExportScreen() {
  const t = useTranslations("checklist.exportScreen");
  const router = useRouter();
  const searchParams = useSearchParams();
  const [projectId, setProjectId] = useState(searchParams.get("projectId") ?? "");
  const [mode, setMode] = useState<ModuleMode>("all");
  const [chosen, setChosen] = useState<string[]>([]);
  const [include, setInclude] = useState<ProjectExportPart[]>(["checklist"]);
  const [filters, setFilters] = useState<Partial<ChecklistItemListParams>>({});
  const [attempted, setAttempted] = useState(false);
  const exporter = useProjectExport();

  const projects = useProjects({
    limit: PROJECT_LIMIT,
    sort: SORT.projects.name,
    sortDirection: "asc",
  });
  // Mirrors the backend gate; it does not replace it. A project the caller can read
  // neither part of would only ever answer 403.
  const exportable = (projects.data?.items ?? []).filter(
    (p) => can(p, PERMISSION.CHECKLIST_READ) || can(p, PERMISSION.MOCKDATA_READ),
  );
  const moreProjects =
    (projects.data?.totalCount ?? 0) > (projects.data?.items.length ?? 0);
  const project = exportable.find((p) => p.id === projectId) ?? null;

  const modules = useChecklistModules(
    {
      projectId,
      limit: MODULE_LIMIT,
      sort: SORT.checklistModules.name,
      sortDirection: "asc",
    },
    { enabled: Boolean(project) },
  );
  const moduleItems = modules.data?.items ?? [];
  const moreModules = (modules.data?.totalCount ?? 0) > moduleItems.length;

  const allowed: Record<ProjectExportPart, boolean> = {
    checklist: project ? can(project, PERMISSION.CHECKLIST_READ) : false,
    mockData: project ? can(project, PERMISSION.MOCKDATA_READ) : false,
  };
  const parts = include.filter((part) => allowed[part]);
  const missingPart = attempted && parts.length === 0;
  const missingModules = attempted && mode === "choose" && chosen.length === 0;

  const backHref = projectId ? `/checklist?projectId=${projectId}` : "/checklist";

  function selectProject(next: ProjectResponse | null) {
    if (!next) return;
    setProjectId(next.id);
    // Module ids belong to one project; carrying them over would 404 the export.
    setChosen([]);
  }

  function togglePart(part: ProjectExportPart, on: boolean) {
    setInclude((current) =>
      on
        ? [...current.filter((p) => p !== part), part]
        : current.filter((p) => p !== part),
    );
  }

  function toggleModule(id: string, on: boolean) {
    setChosen((current) =>
      on ? [...current.filter((m) => m !== id), id] : current.filter((m) => m !== id),
    );
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setAttempted(true);
    if (!project || parts.length === 0) return;
    if (mode === "choose" && chosen.length === 0) return;

    exporter.mutate(
      {
        projectId: project.id,
        params: {
          include: parts,
          moduleIds: mode === "choose" ? chosen : [],
          ...(parts.includes("checklist") ? filters : {}),
        },
      },
      {
        onSuccess: () => {
          toast.success(t("downloaded"));
          router.push(backHref);
        },
      },
    );
  }

  return (
    <FormPage
      backHref={backHref}
      title={t("title")}
      description={t("description")}
      submitLabel={t("submit")}
      isPending={exporter.isPending}
      error={exporter.error}
      onSubmit={handleSubmit}
    >
      <Field>
        <FieldLabel htmlFor="export-project">
          {t("project")} <span className="text-danger-text">*</span>
        </FieldLabel>
        <Combobox
          items={exportable}
          value={project}
          onValueChange={selectProject}
          itemToStringLabel={(p: ProjectResponse) => p.name}
        >
          <ComboboxInput
            className="w-full"
            placeholder={
              projects.isLoading ? t("loadingProjects") : t("searchProjects")
            }
            id="export-project"
          />
          <ComboboxContent>
            <ComboboxEmpty>
              {projects.isLoading ? t("loading") : t("noProjectMatches")}
            </ComboboxEmpty>
            <ComboboxList>
              {(p: ProjectResponse) => (
                <ComboboxItem key={p.id} value={p}>
                  <span className="truncate">{p.name}</span>
                </ComboboxItem>
              )}
            </ComboboxList>
          </ComboboxContent>
        </Combobox>
        {projects.isError ? (
          <ListError error={projects.error} onRetry={() => projects.refetch()} />
        ) : null}
        {moreProjects ? (
          <FieldDescription>
            {t("projectCap", { count: PROJECT_LIMIT })}
          </FieldDescription>
        ) : null}
        {attempted && !project ? <FieldError>{t("chooseProject")}</FieldError> : null}
      </Field>

      {project ? (
        <>
          <FieldSet>
            <FieldLegend variant="label">{t("include")}</FieldLegend>
            <Field orientation="horizontal">
              <Checkbox
                id="include-checklist"
                checked={include.includes("checklist") && allowed.checklist}
                disabled={!allowed.checklist}
                onCheckedChange={(checked) => togglePart("checklist", checked === true)}
              />
              <FieldLabel htmlFor="include-checklist">{t("testChecklist")}</FieldLabel>
            </Field>
            <Field orientation="horizontal">
              <Checkbox
                id="include-mock-data"
                checked={include.includes("mockData") && allowed.mockData}
                disabled={!allowed.mockData}
                onCheckedChange={(checked) => togglePart("mockData", checked === true)}
              />
              <FieldLabel htmlFor="include-mock-data">{t("mockData")}</FieldLabel>
            </Field>
            <FieldDescription>{t("includeHint")}</FieldDescription>
            {missingPart ? <FieldError>{t("chooseWhat")}</FieldError> : null}
          </FieldSet>

          <FieldSet>
            <FieldLegend variant="label">{t("modules")}</FieldLegend>
            <RadioGroup
              aria-label={t("modulesAria")}
              value={mode}
              onValueChange={(value) => setMode(value as ModuleMode)}
              className="flex flex-wrap gap-4"
            >
              <Label className="text-foreground flex items-center gap-2 text-sm font-normal">
                <RadioGroupItem value="all" />
                {modules.data
                  ? t("allModulesCount", { count: modules.data.totalCount })
                  : t("allModules")}
              </Label>
              <Label className="text-foreground flex items-center gap-2 text-sm font-normal">
                <RadioGroupItem value="choose" />
                {t("chooseModules")}
              </Label>
            </RadioGroup>
            {modules.isError ? (
              <ListError error={modules.error} onRetry={() => modules.refetch()} />
            ) : null}
            {mode === "choose" && !modules.isError ? (
              modules.isLoading ? (
                <FieldDescription>{t("loadingModules")}</FieldDescription>
              ) : moduleItems.length === 0 ? (
                <FieldDescription>{t("noModules")}</FieldDescription>
              ) : (
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {moduleItems.map((module) => (
                    <Field key={module.id} orientation="horizontal">
                      <Checkbox
                        id={`module-${module.id}`}
                        checked={chosen.includes(module.id)}
                        onCheckedChange={(checked) =>
                          toggleModule(module.id, checked === true)
                        }
                      />
                      <FieldLabel htmlFor={`module-${module.id}`} className="truncate">
                        {module.name}
                      </FieldLabel>
                    </Field>
                  ))}
                </div>
              )
            ) : null}
            {mode === "choose" && moreModules && !modules.isError ? (
              <FieldDescription>
                {t("moduleCap", { count: MODULE_LIMIT })}
              </FieldDescription>
            ) : null}
            {missingModules ? <FieldError>{t("chooseAtLeastOne")}</FieldError> : null}
          </FieldSet>

          {parts.includes("checklist") ? (
            <FieldSet>
              <FieldLegend variant="label">{t("filters")}</FieldLegend>
              <FieldDescription>{t("filtersHint")}</FieldDescription>
              <ItemFilters currentFilters={filters} onFiltersChange={setFilters} />
            </FieldSet>
          ) : null}
        </>
      ) : null}
    </FormPage>
  );
}
