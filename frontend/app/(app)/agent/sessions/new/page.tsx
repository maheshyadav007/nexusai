import { Suspense } from "react";
import { NewSessionScreen } from "@/ui/features/sessions/NewSessionScreen";

export default function Page() {
  return <Suspense fallback={null}><NewSessionScreen /></Suspense>;
}
