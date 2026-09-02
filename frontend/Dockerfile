# syntax=docker/dockerfile:1
# ---------- Stage 1: build ----------
FROM node:20-alpine AS build

WORKDIR /app

# 国内服务器构建慢主要卡在 npm 下载；compose 里通过 NPM_REGISTRY 传镜像源（默认官方源）
ARG NPM_REGISTRY=https://registry.npmjs.org
RUN npm config set registry "$NPM_REGISTRY"

COPY package.json package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm \
    npm install --no-audit --no-fund

COPY . .
RUN npm run build:docker

# ---------- Stage 2: nginx ----------
FROM nginx:1.27-alpine

ENV TZ=Asia/Tokyo

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
