FROM node:22-bookworm-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
RUN corepack enable && corepack prepare pnpm@10.20.0 --activate
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY scripts/setup-hook.ts scripts/setup-hook.ts
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM node:22-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 ERP_DEPLOYMENT=railway ERP_DATA_DIR=/data/erp
RUN apt-get update && apt-get install -y --no-install-recommends zip unzip && rm -rf /var/lib/apt/lists/* \
 && corepack enable && corepack prepare pnpm@10.20.0 --activate
COPY --from=build /app /app
EXPOSE 3000
CMD ["pnpm", "start"]
