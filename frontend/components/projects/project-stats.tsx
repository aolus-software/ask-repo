import { Card, CardContent } from "@/components/ui/card";
import type { ProjectResponse } from "@/lib/api/types";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <CardContent className="p-6">
        <p className="text-muted-foreground text-sm font-medium">{label}</p>
        <p className="mt-1 text-xl font-semibold">{value}</p>
      </CardContent>
    </Card>
  );
}

export function ProjectStats({ project }: { project: ProjectResponse }) {
  return (
    <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
      <Stat label="Files indexed" value={project.fileCount?.toLocaleString() ?? "—"} />
      <Stat label="Chunks" value={project.chunkCount?.toLocaleString() ?? "—"} />
      <Card>
        <CardContent className="p-6">
          <p className="text-muted-foreground text-sm font-medium">Last indexed commit</p>
          <p className="mt-1 font-mono text-xl font-semibold">
            {project.lastIndexedCommit?.slice(0, 7) ?? "—"}
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardContent className="p-6">
          <p className="text-muted-foreground text-sm font-medium">Embedding model</p>
          <p
            className="mt-1 truncate font-mono text-base font-semibold"
            title={project.embeddingModel ?? undefined}
          >
            {project.embeddingModel ?? "—"}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
