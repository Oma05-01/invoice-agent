import type { NextConfig } from "next";

const backendOrigin =
  process.env.DJANGO_INTERNAL_URL || "http://127.0.0.1:8001";

const nextConfig: NextConfig = {
  reactCompiler: true,

  skipTrailingSlashRedirect: true,

  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendOrigin}/api/:path*/`,
      },
    ];
  },
};

export default nextConfig;