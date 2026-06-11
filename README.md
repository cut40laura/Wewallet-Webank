# 微众钱包 · 小微客户经理智能体

面向小微企业主的贷款客户经理智能体「小微」：网页聊天（Hermes 网关）+ 视频通话（豆包实时语音）+ 风控画像 + 知识库。

## 运行

```bash
./run-customer-manager-ui.sh        # 启动 Web UI（默认 http://127.0.0.1:8787/chat）
```

配置项见 `.env.example`（复制为 `.env` 填入密钥）。

## 开发环境

依赖装在 **anaconda 的 Python**（本机为 `/opt/anaconda3/bin/python3`，即 `python3.13`），
系统自带的 `/usr/bin/python3` 缺 `requests`/`numpy` 等包，跑不起来。换新机器时：

```bash
python3 -m pip install -r requirements.txt
```

## 测试

```bash
/opt/anaconda3/bin/python3 -m unittest discover -s tests        # 全量
/opt/anaconda3/bin/python3 -m unittest tests.test_auth -v       # 单个模块
```

## 目录速览

- `ui/` — Web 服务端（`server.py` 路由表 + 各业务模块）与前端静态资源
- `knowledge/` — 贷款产品/风控/反欺诈知识库源文件
- `tests/` — 单元测试（unittest）
- `scripts/` — 一次性/本地实验脚本（不进公开仓库）
- `deploy/` — Docker / CVM 部署配置
- `simulator/` — 客户模拟器
