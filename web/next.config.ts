import type { NextConfig } from "next";

// Fully static export (Amplify / S3). Dynamic camera pages use /camera?id=... instead of [id] routes.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
};

export default nextConfig;
