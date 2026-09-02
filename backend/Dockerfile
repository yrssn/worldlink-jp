# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Tokyo

WORKDIR /app

# 系统依赖：mysqlclient/cryptography 编译时需要的 build-essential / libffi-dev / libssl-dev
# tini 作为 PID 1，处理信号
# 国内服务器构建可通过 compose 传 APT_MIRROR（如 mirrors.tuna.tsinghua.edu.cn）替换 debian 源
ARG APT_MIRROR=
RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|deb.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        tini \
        libssl-dev \
        libffi-dev \
        ca-certificates \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

# pip 源通过 compose 的 PIP_INDEX_URL 传入（默认官方 PyPI）
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=$PIP_INDEX_URL

COPY requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && pip install -r /app/requirements.txt

COPY . /app

RUN mkdir -p /app/uploads

EXPOSE 8009

ENTRYPOINT ["/usr/bin/tini", "--"]

# 生产用 uvicorn 直跑（不开 reload），workers 通过环境变量控制。
# 默认单 worker：BitBrowser 中继连接按进程存于内存，多 worker 会导致中继请求
# 被负载均衡到没有连接的进程而间歇失败。ws ping 保活避免空闲连接被代理掐断。
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT:-8009} --workers ${UVICORN_WORKERS:-1} --ws-ping-interval 20 --ws-ping-timeout 60 --timeout-keep-alive 75"]
