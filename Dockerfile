FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

# 系统依赖（Playwright chromium 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    cron \
    tzdata \
    wget \
    fonts-noto-cjk \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone

WORKDIR /app

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 先复制依赖文件，利用缓存
COPY pyproject.toml uv.lock ./
COPY TenVision/pyproject.toml TenVision/uv.lock ./TenVision/

RUN uv sync --frozen --no-dev \
    && cd TenVision && uv sync --frozen --no-dev && cd .. \
    && uv run playwright install chromium --with-deps

# 复制源码
COPY rainyun_signin.py ./
COPY TenVision/ ./TenVision/

# cron 配置：每天 9:00 执行
RUN echo '0 9 * * * cd /app && /app/.venv/bin/python rainyun_signin.py >> /var/log/rainyun.log 2>&1' > /etc/cron.d/rainyun \
    && chmod 0644 /etc/cron.d/rainyun \
    && crontab /etc/cron.d/rainyun

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/app/.env"]

ENTRYPOINT ["/entrypoint.sh"]
