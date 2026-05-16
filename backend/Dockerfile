FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=Asia/Tokyo

WORKDIR /app

# 系统依赖：mysqlclient/cryptography 编译时需要的 build-essential / libffi-dev / libssl-dev
# tini 作为 PID 1，处理信号
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        tini \
        libssl-dev \
        libffi-dev \
        ca-certificates \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

# 国内构建可改成清华源（按需取消注释）
# RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
    && pip install -r /app/requirements.txt

COPY . /app

RUN mkdir -p /app/uploads

EXPOSE 8009

ENTRYPOINT ["/usr/bin/tini", "--"]

# 生产用 uvicorn 直跑（不开 reload），workers 通过环境变量控制
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${APP_PORT:-8009} --workers ${UVICORN_WORKERS:-2}"]
