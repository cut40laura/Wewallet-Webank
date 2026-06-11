# CVM 部署说明

目标方案：CVM 4C8G、Docker Compose、Nginx、文件数据卷。

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

## 5. 启动

```bash
docker compose up -d --build
```

检查状态：

```bash
docker compose ps
docker compose logs -f app
```

访问：

```text
http://服务器公网 IP/chat
```

绑定域名和 HTTPS 后访问：

```text
https://你的域名/chat
```

## 5.5 端到端实时语音（通话版小微）+ HTTPS

视频通话的"实时语音"用 StepFun `stepaudio-2.5-realtime`，是 WebSocket 端到端语音，
浏览器调摄像头/麦克风、连 wss **都要求 HTTPS（安全上下文）**，所以必须先配证书。

**a) 环境变量**（`.env`）：
```bash
STEP_API_KEY=你的阶跃key            # platform.stepfun.com 申请；勿提交
WEWALLET_VOICECALL_PROVIDER=stepfun  # 看材料的视觉识别用 step-3.7-flash
WEWALLET_COOKIE_SECURE=1             # 上 HTTPS 后开启
```
其余 realtime 开关（后端=realtime、中继监听 0.0.0.0、同源路径 /voicecall-relay）
已写进 `docker-compose.yml`，无需手动设。中继访问令牌默认每次启动随机生成。

**b) 镜像依赖**：`deploy/hermes-agent-requirements.txt` 已含 `websockets`，
`docker compose up -d --build` 重新构建即装上（中继靠它，缺了实时语音不可用）。

**c) Nginx WebSocket 反代**：`deploy/nginx/wewallet.conf` 已加 `location /voicecall-relay`
反代到 `app:8789`（含 `map $http_upgrade` 与长超时）。

**d) HTTPS 证书**（以腾讯云免费证书为例）：
1. 控制台 → SSL 证书 → 申请免费证书（域名 `www.wewalletpro.online`）→ 验证 → 签发。
2. 下载 **Nginx** 格式，得到 `*_bundle.crt` 和 `*.key`。
3. 传到服务器，放进 `deploy/certs/`，改名为 `fullchain.pem` 和 `privkey.pem`。
4. 打开 `deploy/nginx/wewallet.conf`，**取消文件末尾 443 server 段的整段注释**。
5. `docker compose up -d`（compose 已映射 443 端口、挂载 `deploy/certs`）。
6. 云安全组放行 **443**。

完成后手机/电脑访问 `https://www.wewalletpro.online/chat`，登录进视频通话即可实时对话；
"给小微看材料"会截一帧给 step-3.7-flash 识别后让小微当场转述。

## 6. 备份

手动备份：

```bash
bash deploy/scripts/backup-data.sh
```

建议加定时任务，每天凌晨执行一次，至少保留 14 天。

## 7. 仍需生产化的点

- 当前后端仍是 Python `ThreadingHTTPServer`，已经可以由 Nginx 反代做小规模试点；后续要支持更高并发，建议重构为 ASGI 服务再接 uvicorn/gunicorn。
- AI 对话和画像更新仍是长请求同步执行；试点可以用，正式上线建议接任务队列。
- 用户、企业、会话当前是 JSON 文件；正式对外建议迁移到 TencentDB。
- 上传材料当前落本地数据卷；正式对外建议迁移到 COS。
- 真实短信登录需要接腾讯云短信服务。
