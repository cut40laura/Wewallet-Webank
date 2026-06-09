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
