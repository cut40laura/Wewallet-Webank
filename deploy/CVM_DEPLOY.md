# CVM 部署说明

目标方案：CVM 4C8G、Docker Compose、Caddy（自动 HTTPS）、文件数据卷。

## 1. 服务器准备

- 系统建议：Ubuntu 22.04 LTS 或 24.04 LTS。
- 安全组开放：80、443。调试期才临时开放 8787。
- 安装 Docker 和 Docker Compose 插件。

## 2. 项目目录

建议放在：

```bash
/opt/wewallet
```

运行前创建持久化目录：

```bash
mkdir -p runtime/app_data runtime/ui_data runtime/backups runtime/hermes-agent
```

`runtime/app_data` 保存用户、企业、上传材料、画像、会话等业务数据。  
`runtime/ui_data` 保存知识库 SQLite 索引。  
`runtime/hermes-agent` 放 Hermes agent 代码，容器内会挂载到 `/opt/hermes-agent`。

## 3. 环境变量

复制示例文件：

```bash
cp .env.example .env
```

必须修改：

- `WEWALLET_AUTH_SECRET`：生成新的长随机字符串。
- `WEWALLET_SMS_DEBUG=0`：试点环境不要把验证码打印到日志。
- `WEWALLET_COOKIE_SECURE=1`：HTTPS 下保持开启。

## 4. Hermes 配置

`.hermes-customer-manager/config.yaml` 包含模型服务地址和 API Key，本地文件被 `.gitignore` 忽略，不应提交到 Git。

部署到 CVM 时，需要在服务器上单独放置生产用配置：

```bash
.hermes-customer-manager/config.yaml
```

同时把 Hermes agent 代码放到：

```bash
runtime/hermes-agent
```

容器启动后会使用：

- `HERMES_HOME=/opt/wewallet/hermes-home`
- `HERMES_AGENT_DIR=/opt/hermes-agent`

## 4.5 语音/视频通话（Caddy 自动 HTTPS，无需自签证书）

通话能在本地用、在服务器用不了，是两个硬限制造成的，已用 Caddy 一并解决：

1. **页面必须 HTTPS**：浏览器只在安全上下文（HTTPS 或 localhost）允许 `getUserMedia` 取摄像头/麦克风。纯 IP 的 HTTP 页面一开通话就报"无法获取麦克风/摄像头"。
2. **实时代理必须可达且是 wss**：HTTPS 页面不能连 `ws://`（mixed-content）。

方案：Caddy 在边缘自动申请 **Let's Encrypt 受信任证书**（绿锁、无警告、自动续期），并把 `/` 反代到 app、`/rtc` 反代到内网实时代理。**不用自签证书、不用单独开 8870 端口、不用手动信任。**

### (1) 域名与备案

腾讯云大陆服务器上，未备案域名的 80/443 会被拦截，证书签不下来。**必须用已备案、且 A 记录解析到本机 IP 的自有域名。**
在 `.env` 设 `WEWALLET_SITE_DOMAIN=你的备案域名`。

> Let's Encrypt 签发需要 **80 端口能从公网访问**（你已开放 80/443，无需再开 8870）。

### (2) 配置 `.env` 里的通话凭证

```bash
# 豆包实时语音（二选一）
DOUBAO_REALTIME_APP_ID=...
DOUBAO_REALTIME_ACCESS_KEY=...
# 或 DOUBAO_REALTIME_API_KEY=...

# 视觉/风控/矛盾检测（火山方舟）
ARK_API_KEY=...

# 已备案、解析到本机 IP 的域名
WEWALLET_SITE_DOMAIN=你的备案域名
```

不配豆包/ARK 凭证，通话代理只会进 mock，不是真通话。

### (3) 访问

```text
https://你的备案域名/chat
```

首次启动 Caddy 会自动签证书（约几十秒），之后绿锁、无警告，**网址可直接分享给别人，点开即用**。

## 5. 启动

```bash
docker compose up -d --build
```

检查状态：

```bash
docker compose ps
docker compose logs -f app
docker compose logs -f caddy      # 看证书签发是否成功
docker compose logs -f realtime   # 看通话代理是否就绪
```

访问：

```text
https://你的备案域名/chat
```

> 80 会自动跳转到 443；首次启动需等 Caddy 签发证书（几十秒）。证书签不下来通常是域名未备案或 80 端口不通。

## 6. 备份

手动备份：

```bash
bash deploy/scripts/backup-data.sh
```

建议加定时任务，每天凌晨执行一次，至少保留 14 天。

## 7. 仍需生产化的点

- 当前后端仍是 Python `ThreadingHTTPServer`，已经可以由 Caddy 反代做小规模试点；后续要支持更高并发，建议重构为 ASGI 服务再接 uvicorn/gunicorn。
- AI 对话和画像更新仍是长请求同步执行；试点可以用，正式上线建议接任务队列。
- 用户、企业、会话当前是 JSON 文件；正式对外建议迁移到 TencentDB。
- 上传材料当前落本地数据卷；正式对外建议迁移到 COS。
- 真实短信登录需要接腾讯云短信服务。
