"use client";

import type { ButtonHTMLAttributes } from "react";
import { Pressable } from "@/ui/primitives/Pressable";
import { useAssistant } from "./AssistantProvider";

/** Opening a conversation always starts in the right panel. */
export function SessionLink({ session, className = "", ...props }: { session: string } & ButtonHTMLAttributes<HTMLButtonElement>) {
  const assistant = useAssistant();
  return <Pressable {...props} onClick={() => assistant.openSession(session)} className={`rounded-sm text-left text-accent-default underline underline-offset-2 hover:text-accent-hover ${className}`} />;
}
