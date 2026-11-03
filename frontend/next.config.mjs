import { networkInterfaces } from "node:os";
import appConfig from "./app.config.json" with { type: "json" };

// The same list the backend reads, for reaching the app at any other address.
const extraHosts = (process.env.NEXUSAI_ALLOWED_ORIGINS ?? "").split(",").filter(Boolean).map((origin) => new URL(origin.trim()).hostname);

// This computer's own addresses, so its live connection works when it's opened by IP.
const ownAddresses = Object.values(networkInterfaces()).flat().filter((net) => net?.family === "IPv4").map((net) => net.address);

export default {
  // Compression holds back streamed events until a buffer fills, and this server is local.
  compress: false,
  // Next trusts only localhost in development, and blocks its live connection elsewhere.
  allowedDevOrigins: [...appConfig.devOrigins, ...ownAddresses, ...extraHosts],
  // It would sit on top of the chat's Send button. Build errors still show their own overlay.
  devIndicators: false,
  // Requests pass through proxy.ts, which would cut off an upload past its 10 MB default.
  // The backend's max_upload_bytes is the real limit.
  experimental: { proxyClientMaxBodySize: "210mb" },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.NEXUSAI_BACKEND_URL ?? appConfig.backendUrl}/api/:path*` }];
  },
};
