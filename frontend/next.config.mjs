import appConfig from "./app.config.json" with { type: "json" };

export default {
  // Compression holds back streamed events until a buffer fills, and this server is local.
  compress: false,
  // Next trusts only localhost in development, and blocks its live connection elsewhere.
  allowedDevOrigins: appConfig.devOrigins,
  // It would sit on top of the chat's Send button. Build errors still show their own overlay.
  devIndicators: false,
  // Requests pass through proxy.ts, which would cut off an upload past its 10 MB default.
  // The backend's max_upload_bytes is the real limit.
  experimental: { proxyClientMaxBodySize: "210mb" },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.NEXUSAI_BACKEND_URL ?? appConfig.backendUrl}/api/:path*` }];
  },
};
