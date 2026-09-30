# ---- Build stage: Vite production build ----
FROM node:22-alpine AS build
WORKDIR /build
# 锁文件先复制：只要依赖没变，这层就命中缓存，改代码不会重装 node_modules
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# 先类型检查再打包：类型错误在**构建期**失败，而不是上线后白屏
RUN npm run type-check
RUN npm run build

# ---- Serve stage: nginx with SPA fallback + /api reverse proxy ----
FROM nginx:1.27-alpine
COPY nginx.docker.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/dist /usr/share/nginx/html
# 替换默认站点页，避免暴露 nginx 版本；健康检查用容器内 curl
RUN rm -f /usr/share/nginx/html/index.html.bak \
    && sed -i 's|^nginx/[0-9.]*$|nginx|' /etc/nginx/nginx.conf 2>/dev/null || true
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
EXPOSE 80
