import appConfig from "./app.config.json" with { type: "json" };

export default {
  // Compression holds back streamed events until a buffer fills, and this server is local.
  compress: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${process.env.NEXUSAI_BACKEND_URL ?? appConfig.backendUrl}/api/:path*` }];
  },
};
