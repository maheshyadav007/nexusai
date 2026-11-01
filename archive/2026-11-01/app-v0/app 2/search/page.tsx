import { Command, SearchIcon, Sparkles } from "lucide-react";
import { PageHeader } from "@/components/app/page-header";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { searchResults } from "@/lib/data";

export default function SearchPage() {
  return (
    <>
      <PageHeader
        eyebrow="Search"
        title="Search every work system at once."
        description="Mock universal search over email, calendar, PLM, files, tasks, and issue systems."
      />
      <div className="mx-auto max-w-chat space-y-lg px-xl py-xl">
        <div className="glass-panel rounded-xl p-md">
          <div className="flex items-center gap-sm">
            <SearchIcon className="size-md text-accent" />
            <Input
              defaultValue="supplier risk release blockers today"
              className="border-none bg-transparent px-0 shadow-none focus-visible:shadow-none"
            />
            <Badge variant="default">
              <Command className="size-sm" />
              K
            </Badge>
          </div>
        </div>

        <div className="space-y-sm">
          {searchResults.map((result) => {
            const Icon = result.icon;
            return (
              <Card key={result.id} className="p-md">
                <div className="flex items-start gap-sm">
                  <div className="grid size-2xl shrink-0 place-items-center rounded-lg border border-hairline bg-surface-2">
                    <Icon className="size-md text-accent" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-xs">
                      <h2 className="text-heading text-ink">{result.title}</h2>
                      <Sparkles className="size-sm text-ink-tertiary" />
                    </div>
                    <p className="mt-xxs text-caption text-ink-tertiary">{result.meta}</p>
                    <p className="mt-sm text-small text-ink-subtle">{result.excerpt}</p>
                  </div>
                </div>
              </Card>
            );
          })}
        </div>
      </div>
    </>
  );
}
