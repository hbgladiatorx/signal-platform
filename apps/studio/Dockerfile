# thebayn frontend — TanStack Start (nitro node-server preset).
#
# Build with bun (matches the repo toolchain + bun.lock), run the nitro Node
# server output on a slim node runtime. The build produces dist/{server,client}:
# nitro bundles its own deps under dist/server, so the runtime image only needs
# the dist/ tree and a Node interpreter.
#
# Served same-origin behind Caddy on signal.cimcha.com; the API client defaults
# to VITE_API_BASE=/api, so no build arg is required for the standard deploy.

# ---------- Stage 1: build ----------
FROM oven/bun:1-alpine AS build
WORKDIR /app

# Install dependencies from the lockfile (cached unless deps change).
COPY package.json bun.lock ./
RUN bun install --frozen-lockfile

# Build the app (vite + nitro). VITE_* values are inlined at build time; the
# default API base (/api) is correct for the same-origin Caddy deploy.
COPY . .
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=$VITE_API_BASE
RUN bun run build

# ---------- Stage 2: runtime ----------
# Node 22 (not 20): the Supabase client initializes a Realtime WebSocket during
# SSR, and @supabase/realtime-js requires a native global WebSocket — present in
# Node >=22, absent in 20 (would 500 every SSR render).
FROM node:22-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV HOST=0.0.0.0

RUN addgroup --system --gid 1001 nodejs \
 && adduser --system --uid 1001 web

# dist/ holds server/ (entry + bundled deps) and client/ (static assets) as
# siblings; nitro's node-server resolves the public dir relative to cwd.
COPY --from=build --chown=web:nodejs /app/dist ./

USER web
EXPOSE 3000
CMD ["node", "server/index.mjs"]
