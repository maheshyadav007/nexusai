import { Suspense } from "react";
import { SettingsLayout } from "@/ui/features/settings/SettingsLayout";

export default function SettingsPage() {
  return (
    <Suspense>
      <SettingsLayout />
    </Suspense>
  );
}
