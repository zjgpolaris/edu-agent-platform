# --- 构建阶段 ---
FROM node:20-alpine AS builder
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
# next.config.js 设了 output:"standalone"，产出自包含的 .next/standalone
RUN npm run build

# --- 运行阶段（精简镜像）---
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

# standalone 产物 + 静态资源 + public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0
# standalone 自带 server.js
CMD ["node", "server.js"]
