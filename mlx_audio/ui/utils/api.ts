// Where the MLX-Audio API lives.
//
// The built UI is served by the API server itself, so by default requests go to
// the same address as the page (an empty base URL). When running `npm run dev`
// the UI is on its own port, so it falls back to http://localhost:8000. Set
// NEXT_PUBLIC_API_BASE_URL (and optionally NEXT_PUBLIC_API_PORT) to override.

export function getApiUrl(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL
  const port = process.env.NEXT_PUBLIC_API_PORT
  if (base) return port ? `${base}:${port}` : base
  return process.env.NODE_ENV === "development" ? "http://localhost:8000" : ""
}

// WebSocket URL for an API path such as "/v1/audio/transcriptions/realtime".
// Call this from the browser only (it reads window.location).
export function getWsUrl(path: string): string {
  const httpBase = getApiUrl() || window.location.origin
  return httpBase.replace(/^http/, "ws") + path
}
