# Rainyun 每日签到自动化

自动完成雨云每日签到，包括腾讯点选验证码识别。

## 快速开始

### 1. 配置账号

在项目根目录创建 `.env` 文件：

```
username: 你的账号
password: 你的密码
```

### 2. 构建并运行

```bash
docker compose up -d --build
```

容器内 cron 默认每天 **09:00 (Asia/Shanghai)** 自动执行签到。

### 3. 查看日志

```bash
docker exec rainyun-signin tail -f /var/log/rainyun.log
```

### 4. 手动执行一次

```bash
docker exec rainyun-signin /app/.venv/bin/python /app/rainyun_signin.py
```

### 5. 修改执行时间

编辑 `Dockerfile` 中的 cron 表达式后重新构建：

```
0 9 * * *    # 每天 9:00
0 10 * * *   # 每天 10:00
30 8 * * *   # 每天 8:30
```

## 致谢

本项目使用 [TenVision](https://github.com/AmethystDev-Labs/TenVision) 作为腾讯点选验证码的识别引擎，感谢作者的出色工作。

TenVision 基于 [MIT 协议](https://github.com/AmethystDev-Labs/TenVision/blob/master/LICENSE) 开源，版权归属 Starry-Sky-World，本项目已保留其原始 LICENSE 文件（`TenVision/LICENSE`）。
