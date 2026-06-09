# 用户模拟器（Simulator）

用 DeepSeek 驱动一个"假客户"，自动和本地客户经理（`ui/server.py`）多轮对话，
逐轮打分、按"厌烦度"模型自主决定何时结束，产出可分析的对话日志与客户评价。

```
DeepSeek（假客户大脑） → /api/chat（客户经理） → Evaluator（打分） → logs/*.json + *.txt
```

## 与本项目的对接（已适配）

- **端口**：默认连 `http://127.0.0.1:8787`（本地 `server.py` 的默认端口）。
  如改了端口，用环境变量覆盖：`export WEWALLET_BASE=http://127.0.0.1:8866`
- **零额外依赖**：仅用 Python 标准库（已去掉 `pyyaml`，frontmatter 用内置解析）。
- **`.env` 自动加载**：会读取项目根的 `.env`。
- **OpenAI 兼容**：假客户大脑用 `SIMULATOR_LLM_*` 配置，支持任意 OpenAI 兼容端点。
- **不污染记忆**：跑测前清空 `.hermes-customer-manager/memories/` 做信息隔离，
  跑完会**自动还原**原始内容（见 `clear_agent_memory` / `restore_agent_memory`）。

## 快速开始

```bash
# 1. 配置假客户大脑（独立于项目后端 LLM）——写进项目根 .env：
#    SIMULATOR_LLM_API_KEY=sk-xxxx
#    SIMULATOR_LLM_BASE_URL=https://api.svips.org/v1
#    SIMULATOR_LLM_MODEL=GLM-5.1

# 2. 启动本地客户经理服务（另开一个终端）
./run-customer-manager-ui.sh             # 监听 8787

# 3. 播种测试账号（首次运行一次即可，幂等）
python3.13 simulator/seed_personas.py

# 4. 单个客户跑测
python3.13 simulator/user_simulator.py --persona laowang --max-turns 10

# 5. 五个客户批量跑测 + 对比报告
python3.13 simulator/batch_run.py
```

> 用 `python3.13`：本地依赖（numpy 等）装在 3.13 上，和 `run-customer-manager-ui.sh` 一致。

> 环境变量优先级：`SIMULATOR_LLM_*` > 旧的 `DEEPSEEK_*`（向后兼容）。

## 客户画像

`personas/*.md`，文件名即 persona key。frontmatter 存结构化参数
（`patience`/`politeness`/`suspicion` 等），正文是人设提示词。
**新增客户只需丢一个 `.md`**，无需改代码；新账号记得跑一次 `seed_personas.py`。

| key | 客户 | 行业 |
|:--|:--|:--|
| laowang | 老王 | 餐饮 |
| xiaoqin | 小琴姐 | 美容 |
| laochen | 老陈 | 五金建材 |
| alex | Alex | 跨境电商 |
| laozhou | 老周 | 模具制造 |

## 输出

- `logs/<persona>_<时间>.json` — 完整结构化日志（逐轮评分、厌烦度轨迹）
- `logs/<persona>_<时间>.txt` — 人类可读对话记录 + 客户评价
- `memory/<id>.json` — 该客户的长期满意度记忆
- `batch_run.py` 额外产出 `logs/batch_summary_<时间>.json`

（`logs/`、`memory/` 已在 `.gitignore` 中忽略。）
