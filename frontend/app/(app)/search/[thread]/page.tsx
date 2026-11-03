import { Suspense } from "react";
import { SearchThread } from "@/ui/features/search/SearchScreen";

export default async function Page({ params }: { params: Promise<{ thread: string }> }) {
  const { thread } = await params;
  return (
    <Suspense>
      <SearchThread id={Number(thread)} />
    </Suspense>
  );
}
