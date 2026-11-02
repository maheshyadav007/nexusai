import { Suspense } from "react";
import { ReaderScreen } from "@/ui/features/documents/ReaderScreen";

export default function Page() {
  return (
    <Suspense>
      <ReaderScreen />
    </Suspense>
  );
}
