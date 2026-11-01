import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Providers } from "@/ui/Providers";
import { t } from "@/ui/strings";
import { fontVariables } from "@/ui/theme/fonts";
import { applySavedAppearance } from "@/ui/theme/ThemeProvider";
import "./globals.css";

export const metadata: Metadata = { title: t("app.name"), description: t("app.description") };

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" className={fontVariables} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: applySavedAppearance }} />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
