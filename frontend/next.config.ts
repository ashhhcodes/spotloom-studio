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

    return [
      {
        source: "/api/adforge/auth/identity",
        destination: `${backendUrl.origin}${basePath}/auth/identity`,
      },
      {
        source: "/api/adforge/projects",
        destination: `${backendUrl.origin}${basePath}/projects`,
      },
      {
        source: "/api/adforge/projects/:projectId/creative-workspace",
        destination: `${backendUrl.origin}${basePath}/projects/:projectId/creative-workspace`,
      },
      {
        source: "/api/adforge/projects/:projectId",
        destination: `${backendUrl.origin}${basePath}/projects/:projectId`,
      },
      {
        source: "/api/adforge/validate/preproduction",
        destination: `${backendUrl.origin}${basePath}/validate/preproduction`,
      },
      {
        source: "/api/adforge/validate/production-package",
        destination: `${backendUrl.origin}${basePath}/validate/production-package`,
      },
      {
        source: "/api/adforge/render/demo",
        destination: `${backendUrl.origin}${basePath}/render/demo`,
      },
    ];
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
