#!/bin/sh
set -e

# 确保 .env 存在
if [ ! -f /app/.env ]; then
    echo "错误: 未挂载 .env 文件，请使用 -v /path/to/.env:/app/.env" >&2
    exit 1
fi

# 打印下次执行时间
echo "[$(date '+%Y-%m-%d %H:%M:%S')] rainyun-signin 已启动，cron 定时每天 09:00 执行"
echo "当前 crontab:"
crontab -l

# 前台运行 cron
exec cron -f
