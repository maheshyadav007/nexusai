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

const REFUSED = "This address isn't allowed to reach NexusAI. Open the app by its IP address, or add this address to NEXUSAI_ALLOWED_ORIGINS.";

function allowedOrigins(): string[] {
  const extra = (process.env.NEXUSAI_ALLOWED_ORIGINS ?? "").split(",").map((origin) => origin.trim().replace(/\/$/, ""));
  return [...appConfig.allowedOrigins, ...extra.filter(Boolean)];
}

/** Hands this install's token to requests from the app's own pages, and to nothing else. */
export function proxy(request: NextRequest) {
  const site = request.headers.get("sec-fetch-site");
  const origin = request.headers.get("origin");
  // Any website can make a browser send this, so only the addresses named get the token.
  if ((site === "cross-site" || site === "same-site") && !(origin && allowedOrigins().includes(origin))) {
    return NextResponse.json({ code: "request.refused", message: REFUSED }, { status: 403 });
  }
  const headers = new Headers(request.headers);
  const value = installToken();
  if (value) headers.set(appConfig.installToken.header, value);
  const desktopBackend = process.env.NEXUSAI_DESKTOP_BACKEND_URL;
  if (desktopBackend) {
    const target = new URL(request.nextUrl.pathname + request.nextUrl.search, desktopBackend);
    if (target.hostname !== "127.0.0.1" || target.protocol !== "http:") {
      return NextResponse.json({ message: "Invalid desktop backend address." }, { status: 503 });
    }
    return NextResponse.rewrite(target, { request: { headers } });
  }
  return NextResponse.next({ request: { headers } });
}

export const config = { matcher: "/api/:path*" };
