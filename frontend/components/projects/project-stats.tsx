import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { ProjectResponse } from "@/lib/api/types";

/**
 * One stat tile, one size, used by every caller (`docs/ui-audit-findings.md` §U10.3) —
 * previously two hand-rolled copies that disagreed with each other's value size.
 */
function Stat({
  label,
  value,
  mono = false,
  title,
}: {
  label: string;
  value: string;
  mono?: boolean;
  title?: string;
}) {
  return (
    <Card>
      <CardContent className="p-6">
        <p className="text-muted-foreground text-sm font-medium">{label}</p>
        <p
          className={cn("mt-1 truncate text-xl font-semibold", mono && "font-mono")}
          title={title}
        >
          {value}
        </p>
      </CardContent>
    </Card>
  );
}

export function ProjectStats({ project }: { project: ProjectResponse }) {
  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
      <Stat label="Files indexed" value={project.fileCount?.toLocaleString() ?? "—"} />
      <Stat label="Chunks" value={project.chunkCount?.toLocaleString() ?? "—"} />
      <Stat
        label="Last indexed commit"
        value={project.lastIndexedCommit?.slice(0, 7) ?? "—"}
        mono
      />
      <Stat
        label="Embedding model"
        value={project.embeddingModel ?? "—"}
        mono
        title={project.embeddingModel ?? undefined}
      />
    </div>
  );
}
