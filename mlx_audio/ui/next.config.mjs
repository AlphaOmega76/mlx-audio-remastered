/** @type {import('next').NextConfig} */
const nextConfig = {
  // Build the UI as static files (mlx_audio/ui/out) that the API server serves
  // itself, so the whole app runs from a single port.
  output: "export",
  // Emit /page/index.html so the API server can serve pages from plain folders.
  trailingSlash: true,
  // The codebase has many pre-existing style-lint warnings; don't let them block
  // a build. Type checking still runs, and `npm run lint` is still available.
  eslint: { ignoreDuringBuilds: true },
  // Hide the floating Next.js dev tools "N" button (dev mode only)
  devIndicators: false,
};

export default nextConfig;
