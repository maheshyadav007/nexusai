import { CheckCircle2, ListFilter, Sparkles } from "lucide-react";
import { PageHeader } from "@/components/app/page-header";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ActionTable } from "@/components/work/action-table";
import { actionItems } from "@/lib/data";

export default function TasksPage() {
  return (
    <>
      <PageHeader
        eyebrow="Tasks"
        title="Today's work, ranked by consequence."
        description="Action items are inferred from emails, reminders, PLM issues, and meetings."
        actions={
          <Button variant="secondary">
            <ListFilter className="size-sm" />
            Group
          </Button>
        }
      />
      <div className="mx-auto max-w-page space-y-lg px-xl py-xl">
        <div className="grid gap-md lg:grid-cols-4">
          {[
            ["Critical", "1"],
            ["High", "2"],
            ["Delegated", "2"],
            ["AI prepared", "1"]
          ].map(([label, value]) => (
            <Card key={label} className="p-md">
              <div className="mb-lg flex items-center justify-between">
                <CheckCircle2 className="size-md text-accent" />
                <Sparkles className="size-sm text-ink-tertiary" />
              </div>
              <p className="text-title text-ink">{value}</p>
              <p className="text-small text-ink-subtle">{label}</p>
            </Card>
          ))}
        </div>
        <Card className="p-lg">
          <div className="mb-md">
            <h2 className="text-heading text-ink">Action item table</h2>
            <p className="mt-xxs text-small text-ink-subtle">
              Mock actions generated from the same data used in the chat response.
            </p>
          </div>
          <ActionTable items={actionItems} />
        </Card>
      </div>
    </>
  );
}
