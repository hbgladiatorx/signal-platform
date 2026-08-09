import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { getDevStrategies } from "@/lib/api/studio";
import { Card } from "@/components/ui/card";
import { StageBadge } from "@/components/common/StageBadge";
import { Inbox } from "lucide-react";

export const Route = createFileRoute("/studio/submissions")({
  head: () => ({ meta: [{ title: "Submissions — Bayn Studio" }] }),
  component: Submissions,
});

const STAGES = ["Submitted", "Under Review", "Pipeline Validation", "Human Review", "Accepted", "Rejected"] as const;

function Submissions() {
  const { data } = useQuery({ queryKey: ["devStrategies"], queryFn: getDevStrategies });
  const submitted = (data ?? []).filter((s) => s.submissionStatus);

  return (
    <div className="space-y-5 p-4 md:p-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Bayn submissions</h1>
        <p className="text-sm text-muted-foreground">Strategies you've submitted to Bayn for catalog inclusion.</p>
      </div>

      <div className="grid grid-cols-6 gap-2 text-xs text-muted-foreground">
        {STAGES.map((s) => <div key={s} className="rounded-md border border-border bg-elevated px-2 py-2 text-center font-mono uppercase tracking-wider">{s}</div>)}
      </div>

      {submitted.length === 0 ? (
        <Card className="border-border bg-elevated p-10 text-center text-sm text-muted-foreground">
          <Inbox className="mx-auto mb-3 size-8 opacity-50" />
          You haven't submitted any strategies yet. Strategies must pass out-of-sample testing and at least 30 days of live forward testing before submission.
        </Card>
      ) : (
        <div className="space-y-3">
          {submitted.map((s) => (
            <Card key={s.id} className="border-border bg-elevated p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold">{s.name}</h3>
                    <StageBadge stage={s.submissionStatus as any} />
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground">{s.description}</p>
                  {s.submissionNotes && (
                    <p className="mt-3 rounded-md border border-violet/30 bg-violet/5 p-3 text-sm text-violet/90">
                      <span className="font-semibold">Reviewer note:</span> {s.submissionNotes}
                    </p>
                  )}
                </div>
                <div className="text-right text-xs font-mono text-muted-foreground">
                  {Math.floor((Date.now() - new Date(s.createdAt).getTime()) / 86400000)}d in queue
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
