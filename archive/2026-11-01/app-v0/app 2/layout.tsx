import type { Metadata } from "next";
import { AppShell } from "@/components/app/app-shell";
import { ThemeProvider } from "@/components/app/theme-provider";
import "./globals.css";

export const metadata: Metadata = {
  title: "NexusAI",
  description: "An AI-first personal work assistant prototype."
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="editorial" data-mode="light">
      <body>
        <ThemeProvider />
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
