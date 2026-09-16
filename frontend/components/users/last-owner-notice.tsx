import Link from "next/link";

import { Alert } from "@/components/ui/alert";
import { ApiError } from "@/lib/api/errors";

interface BlockingProject {
  id: string;
  name: string;
}

/**
 * The `409 LAST_OWNER` refusal, rendered as the projects that are blocking rather
 * than as a generic banner. "No" is not actionable; "no, because these three
 * projects would have no owner" is — and each name links to where it gets fixed.
 */
export function LastOwnerNotice({ error }: { error: unknown }) {
  if (!(error instanceof ApiError) || error.code !== "LAST_OWNER") return null;

  const projects = (error.extra.projects ?? []) as BlockingProject[];

  return (
    <Alert role="alert" className="bg-card text-card-foreground border-border">
      <p className="text-sm">
        These projects would be left with no owner. Give someone else the owner role
        first.
      </p>
      <ul className="mt-2 space-y-1 text-sm">
        {projects.map((project) => (
          <li key={project.id}>
            <Link href={`/projects/${project.id}`} className="underline">
              {project.name}
            </Link>
          </li>
        ))}
      </ul>
    </Alert>
  );
}
