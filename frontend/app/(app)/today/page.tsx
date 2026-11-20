import { Suspense } from "react";
import { TodayScreen } from "@/ui/features/today/TodayScreen";

export default function TodayPage() {
  // Today reads its tab and matter from the address.
  return (
    <Suspense fallback={null}>
      <TodayScreen />
    </Suspense>
  );
}
