import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  // La compression mettrait en tampon les flux SSE relayés par le proxy /api.
  compress: false,
};

export default nextConfig;
