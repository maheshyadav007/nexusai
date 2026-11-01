"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useHomeStatus } from "@/ui/client/home";
import { Button } from "@/ui/primitives/Button";
import { Skeleton } from "@/ui/primitives/Skeleton";
import { t } from "@/ui/strings";
import { HomeChooser } from "./HomeChooser";

export function HomeRecovery() {
  const router = useRouter();
  const home = useHomeStatus();
  const [choosingNew, setChoosingNew] = useState(false);
  useEffect(() => {
    if (home.data && home.data.state !== "missing") router.replace("/");
  }, [home.data, router]);
  const data = home.data;
  return (
    <main className="mx-auto flex min-h-screen max-w-dialog flex-col justify-center gap-5 p-6 text-ink-primary">
      <h1 className="font-serif text-display">{t("recover.title")}</h1>
      {data?.state !== "missing" ? (
        <Skeleton className="h-6 w-full" />
      ) : (
        <>
          <p className="text-md text-ink-secondary">{data.message}</p>
          <p className="break-all rounded-md bg-surface-sunken p-3 font-mono text-sm text-ink-secondary">{data.path}</p>
          {choosingNew ? (
            <>
              <p className="text-md text-ink-secondary">{t("recover.new.description")}</p>
              <HomeChooser key="new" initialPath={data.default_path} action={t("recover.new.action")} onChosen={() => router.replace("/")} />
              <Button variant="quiet" onClick={() => setChoosingNew(false)}>
                {t("recover.locate.back")}
              </Button>
            </>
          ) : (
            <>
              <p className="text-md text-ink-secondary">{t("recover.locate.description")}</p>
              <HomeChooser key="locate" initialPath={data.path ?? data.default_path} mustExist action={t("recover.locate.action")} onChosen={() => router.replace("/")} />
              <Button variant="quiet" onClick={() => setChoosingNew(true)}>
                {t("recover.new.switch")}
              </Button>
            </>
          )}
        </>
      )}
    </main>
  );
}
