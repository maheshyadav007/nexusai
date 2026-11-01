"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Input } from "@/ui/primitives/Input";
import { t } from "@/ui/strings";

export function SearchBox() {
  const router = useRouter();
  const [text, setText] = useState("");
  return (
    <form
      role="search"
      className="min-w-0 flex-1"
      onSubmit={(event) => {
        event.preventDefault();
        if (text.trim()) router.push(`/search?q=${encodeURIComponent(text.trim())}`);
      }}
    >
      <Input aria-label={t("search.label")} placeholder={t("search.placeholder")} value={text} onChange={(event) => setText(event.target.value)} />
    </form>
  );
}
