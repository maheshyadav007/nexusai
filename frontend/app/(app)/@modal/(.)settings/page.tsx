import { Suspense } from "react";
import { SettingsModal } from "@/ui/features/settings/SettingsLayout";

// Clicking through to Settings opens it over the page you're on. A direct link gets the full page.
export default function SettingsOverPage() {
  return (
    <Suspense>
      <SettingsModal />
    </Suspense>
  );
}
