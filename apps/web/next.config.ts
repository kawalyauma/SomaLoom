import type { NextConfig } from "next";
const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [{source: "/api/v1/:path*", destination: `${process.env.API_INTERNAL_URL || "http://localhost:8000"}/api/v1/:path*`}];
  },
};
export default config;
