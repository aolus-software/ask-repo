const MILESTONES = [
  { id: "M0", label: "Auth & accounts" },
  { id: "M1", label: "Project ingestion" },
  { id: "M2", label: "Dev Knowledge" },
  { id: "M3", label: "LangGraph" },
  { id: "M4", label: "QA List" },
  { id: "M5", label: "Mock Data Generator" },
];

export default function Home() {
  return (
    <div className="bg-background flex flex-1 items-center justify-center p-6">
      <main className="border-border bg-card w-full max-w-xl rounded-lg border p-8 shadow-sm">
        <p className="text-primary text-sm font-medium">AskRepo</p>

        <h1 className="text-card-foreground mt-2 text-3xl font-semibold tracking-tight">
          Ask questions about a codebase
        </h1>

        <p className="text-muted-foreground mt-3 text-base leading-7">
          Grounded, cited answers over an indexed repository. Self-hosted,
          single-tenant, internal only.
        </p>

        <div className="bg-muted mt-6 rounded-md px-4 py-3">
          <p className="text-muted-foreground text-sm">
            <span className="text-accent-foreground font-medium">Status: pre-M0.</span>{" "}
            The API serves health checks. No feature below is built yet.
          </p>
        </div>

        <ul className="mt-6 space-y-2">
          {MILESTONES.map((milestone) => (
            <li
              key={milestone.id}
              className="text-muted-foreground flex items-center gap-3 text-sm"
            >
              <span className="text-muted-foreground w-8 shrink-0 font-mono text-xs">
                {milestone.id}
              </span>
              <span>{milestone.label}</span>
            </li>
          ))}
        </ul>
      </main>
    </div>
  );
}
