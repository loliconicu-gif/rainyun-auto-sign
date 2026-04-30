# Rainyun 每日签到自动化

自动完成雨云每日签到，包括腾讯点选验证码识别。

## 快速开始

### 1. 配置账号

推荐在项目根目录创建 `accounts/` 目录，每个文件代表一个账号：

```text
accounts/
  account1.env
  account2.env
```

文件内容示例：

```text
username: 你的账号
password: 你的密码
```

如果只想跑单账号，也推荐在 `accounts/` 中只放一个账号文件。

### 2. 构建镜像

```bash
docker compose build
```

容器默认执行一次签到后退出，不再常驻运行。定时调度由**宿主机 cron**负责。

如果你是从旧版常驻容器升级，先停掉旧容器：

```bash
docker compose down --remove-orphans
```

### 3. 手动执行

多账号或单账号（统一使用账号目录）：

```bash
docker compose run --rm rainyun-signin
```

如需只执行某个账号文件：

```bash
docker compose run --rm rainyun-signin --env /app/accounts/account1.env
```

如果你是在容器外直接运行脚本，仍然可以用 `uv run python rainyun_signin.py --env /path/to/account.env` 指定单个账号文件。

### 4. 配置宿主机 cron

宿主机上执行 `crontab -e`，添加例如每天 09:00 执行：

```cron
0 9 * * * cd /root/rainyun-auto-sign && docker compose run --rm rainyun-signin >> /root/rainyun-auto-sign/rainyun.log 2>&1
```

如果你只跑单账号，也可以在 `accounts/` 目录里只保留一个账号文件，cron 命令无需变化。

### 5. 查看日志

如果使用上面的宿主机 cron 重定向：

```bash
tail -f rainyun.log
```

## 致谢

本项目使用 [TenVision](https://github.com/AmethystDev-Labs/TenVision) 作为腾讯点选验证码的识别引擎，感谢作者的出色工作。

同时感谢 [linux.do](https://linux.do) 社区。

TenVision 基于 [MIT 协议](https://github.com/AmethystDev-Labs/TenVision/blob/master/LICENSE) 开源，版权归属 Starry-Sky-World，本项目已保留其原始 LICENSE 文件（`TenVision/LICENSE`）。
