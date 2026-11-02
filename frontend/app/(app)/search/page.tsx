import { Suspense } from "react";
import { SearchScreen } from "@/ui/features/search/SearchScreen";

export default function Page() {
  return (
    <Suspense>
      <SearchScreen />
    </Suspense>
  );
}
