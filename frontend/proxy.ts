import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { NextResponse, type NextRequest } from "next/server";
import appConfig from "./app.config.json";

/** The same folder as app_data_dir in the backend's kernel/home.py. */
function appDataDir(): string {
  if (process.env.NEXUSAI_APP_DATA) return process.env.NEXUSAI_APP_DATA;
  if (process.platform === "win32") return join(process.env.APPDATA ?? homedir(), "NexusAI");
  if (process.platform === "darwin") return join(homedir(), "Library", "Application Support", "NexusAI");
  return join(homedir(), ".config", "nexusai");
}

let token: string | null = null;

// The backend writes it when it starts, which may be after this server does.
function installToken(): string | null {
  if (token) return token;
  try {
    token = readFileSync(join(appDataDir(), appConfig.installToken.file), "utf8").trim() || null;
  } catch {
    token = null;
  }
  return token;
}

/** Hands this install's token to requests from the app's own pages, and to nothing else. */
export function proxy(request: NextRequest) {
  const site = request.headers.get("sec-fetch-site");
  if (site === "cross-site" || site === "same-site") {
    return NextResponse.json({ code: "request.refused", message: "Request refused" }, { status: 403 });
  }
  const headers = new Headers(request.headers);
  const value = installToken();
  if (value) headers.set(appConfig.installToken.header, value);
  return NextResponse.next({ request: { headers } });
}

export const config = { matcher: "/api/:path*" };
