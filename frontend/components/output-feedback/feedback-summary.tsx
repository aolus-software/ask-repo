import { REASON_LABELS } from "@/components/output-feedback/reason-labels";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { FeedbackFeature, FeedbackSummary as Summary } from "@/lib/api/types";

export const FEATURE_LABELS: Record<FeedbackFeature, string> = {
  answer: "Ask answers",
  refine_checklist: "Checklist chat",
  refine_mock_data: "Mock-data chat",
  generate_checklist: "Checklist generation",
  propose_checklist: "Checklist chat proposals",
  generate_mock_data: "Mock-data generation",
  propose_mock_data: "Mock-data chat proposals",
};

function downRate(up: number, down: number): string {
  const total = up + down;
  return total === 0 ? "—" : `${Math.round((down / total) * 100)}%`;
}

export function FeedbackSummary({ summary }: { summary: Summary }) {
  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {summary.byFeature.map((row) => (
          <Card key={row.feature}>
            <CardHeader>
              <CardTitle className="text-sm font-medium">{FEATURE_LABELS[row.feature]}</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-2xl font-semibold">{downRate(row.up, row.down)}</p>
              <p className="text-muted-foreground text-xs">
                down-voted · {row.up + row.down} votes
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Feature</TableHead>
                <TableHead>Reason</TableHead>
                <TableHead className="text-right">Count</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {summary.byReason.map((row) => (
                <TableRow key={`${row.feature}-${row.reasonCode}`}>
                  <TableCell>{FEATURE_LABELS[row.feature]}</TableCell>
                  <TableCell>{REASON_LABELS[row.reasonCode]}</TableCell>
                  <TableCell className="text-right">{row.count}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>

        <Card className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Prompt version</TableHead>
                <TableHead className="text-right">Votes</TableHead>
                <TableHead className="text-right">Down-voted</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {summary.byPromptVersion.map((row) => (
                <TableRow key={row.promptVersion}>
                  <TableCell className="font-mono text-xs">{row.promptVersion}</TableCell>
                  <TableCell className="text-right">{row.up + row.down}</TableCell>
                  <TableCell className="text-right">{downRate(row.up, row.down)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      </div>
      <p className="text-muted-foreground text-xs">
        A vote is stamped with the prompt version running when it was cast, which for a change
        set reviewed days later can be newer than the one that generated it.
      </p>
    </div>
  );
}
