import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    const configuredBase = process.env.NEXT_PUBLIC_ADFORGE_API_BASE_URL ?? "http://127.0.0.1:8000";
    let backendUrl: URL;
    try {
      backendUrl = new URL(configuredBase);
    } catch {
      throw new Error("NEXT_PUBLIC_ADFORGE_API_BASE_URL must be an absolute HTTP(S) URL.");
    }
    if ((backendUrl.protocol !== "http:" && backendUrl.protocol !== "https:")
      || backendUrl.username || backendUrl.password || backendUrl.search || backendUrl.hash) {
      throw new Error("NEXT_PUBLIC_ADFORGE_API_BASE_URL must be an HTTP(S) base URL without credentials, query, or fragment.");
    }
    const basePath = backendUrl.pathname.replace(/\/+$/, "");

    return [{
      source: "/api/adforge/validate/preproduction",
      destination: `${backendUrl.origin}${basePath}/validate/preproduction`,
    }];
  },
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
