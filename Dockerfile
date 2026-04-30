FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

# 系统依赖（Playwright chromium 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
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

VOLUME ["/app/accounts"]

ENTRYPOINT ["/app/.venv/bin/python", "/app/rainyun_signin.py"]
CMD ["--env-dir", "/app/accounts"]
