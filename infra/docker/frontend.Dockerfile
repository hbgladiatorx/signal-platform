# Multi-stage build for the Next.js frontend.
#
# Stage 1 (deps): install node_modules once and cache aggressively.
# Stage 2 (builder): build the standalone Next.js output.
# Stage 3 (runner): minimal runtime image with only the built artifacts.

# ---------- Stage 1: deps ----------
FROM node:20-alpine AS deps
WORKDIR /app

# Alpine ships without libc symlinks Node sometimes wants
RUN apk add --no-cache libc6-compat

# Install deps from lockfile. We accept either package-lock.json or
# yarn.lock; npm is the default if neither is present.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund

# ---------- Stage 2: builder ----------
FROM node:20-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY frontend/ ./

# These NEXT_PUBLIC_* vars must be available at build time, because Next.js
# bakes them into the client bundle. They're passed via docker compose
# build args / env.
ARG NEXT_PUBLIC_AUTH0_DOMAIN
ARG NEXT_PUBLIC_AUTH0_CLIENT_ID
ARG NEXT_PUBLIC_AUTH0_AUDIENCE
ARG NEXT_PUBLIC_AUTH0_CALLBACK_URL
ARG NEXT_PUBLIC_API_BASE
ENV NEXT_PUBLIC_AUTH0_DOMAIN=$NEXT_PUBLIC_AUTH0_DOMAIN
ENV NEXT_PUBLIC_AUTH0_CLIENT_ID=$NEXT_PUBLIC_AUTH0_CLIENT_ID
ENV NEXT_PUBLIC_AUTH0_AUDIENCE=$NEXT_PUBLIC_AUTH0_AUDIENCE
ENV NEXT_PUBLIC_AUTH0_CALLBACK_URL=$NEXT_PUBLIC_AUTH0_CALLBACK_URL
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE

ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# ---------- Stage 3: runner ----------
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Create non-root user
RUN addgroup --system --gid 1001 nodejs \
 && adduser --system --uid 1001 nextjs

# Copy the standalone output. `output: 'standalone'` in next.config.js
# bundles only what's needed.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME=0.0.0.0

CMD ["node", "server.js"]
