# ---------- Stage 1: build ----------
FROM node:20-alpine AS build

WORKDIR /app

# 加速可改 npm 镜像
# RUN npm config set registry https://registry.npmmirror.com

COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .
RUN npm run build

# ---------- Stage 2: nginx ----------
FROM nginx:1.27-alpine

ENV TZ=Asia/Tokyo

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
