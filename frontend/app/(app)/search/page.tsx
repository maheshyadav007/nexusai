import { Suspense } from "react";
import { SearchScreen } from "@/ui/features/mail/SearchScreen";

export default function Page() {
  return (
    <Suspense>
      <SearchScreen />
    </Suspense>
  );
}
