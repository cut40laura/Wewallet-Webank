# 视频通话持久化 — 设计文档

日期：2026-06-08

## 背景

视频通话当前是「用户 ↔ AI 客户经理」的实时音视频对话，由三层构成：

- **前端**（[ui/static/chat.js](../../../ui/static/chat.js)）：`getUserMedia` 取摄像头/麦克风，每 2s 抽帧。
- **Node 代理**（[realtime/doubao-realtime-proxy.mjs](../../../realtime/doubao-realtime-proxy.mjs)，`:8870`）：实时语音转发（豆包 dialogue）、`/api/vision` 视觉理解、`/api/video-chat` 文字兜底。
- **Python 服务**（[ui/server.py](../../../ui/server.py)）：鉴权 + SQLite 持久化。

问题：通话内容、画面观察、反欺诈判断**全程零持久化**，挂断即丢，无尽调留痕。

## 目标

挂断后在数据库保存：① 对话转写 ② 逐帧视觉观察 ③ 风控/反欺诈结论 ④ 通话元数据。"先只存不展示"——本期不做历史查看页，仅落库 + 一个验证用 GET。

## 架构定位

保持边界清晰：

- **Node 代理 = 所有 AI/ML**（实时语音、视觉、文字兜底，新增风控总结）。
- **Python 服务 = 鉴权 + 持久化**（已持有 `enterprise_id`/session 与 SQLite）。

Python 端**不引入 ARK 凭证**：风控结论由代理产出，浏览器随通话记录一并提交 Python 存储。凭证集中在代理一处。

## 数据流

```
接通  → 浏览器 POST /api/video-call/start (Python, 带 session cookie)
        → 建一行 status='active'，返回 call_id
通话中→ 浏览器累积 transcriptLog[]（{role,text,ts}）与 observationsLog[]（结构化观察+ts），仅内存
挂断  → ① POST {transcript,observations} 到代理 /api/risk-summary
            → 规则聚合（anomaly/off_screen/person 计数）+ ARK 文本模型总结
            → {level, reasons[], signals{}}（best-effort，失败则 null）
        ② POST /api/video-call/{call_id}/complete (Python)
            → 写入 transcript/observations/risk/metadata，status='completed'
异常关闭 → beforeunload 用 sendBeacon 尽力补 complete（跳过风控总结）
```

## 数据库

[ui/db.py](../../../ui/db.py) `SCHEMA` 新增一张表，JSON 列风格沿用 `messages`：

```sql
CREATE TABLE IF NOT EXISTS video_calls (
    id            TEXT PRIMARY KEY,      -- call_id (服务端 uuid4)
    enterprise_id TEXT NOT NULL,
    user_id       TEXT,
    started_at    TEXT NOT NULL,         -- iso_now()
    ended_at      TEXT,                  -- null 直到 complete
    status        TEXT NOT NULL,         -- 'active' | 'completed'
    transcript    TEXT,                  -- JSON: [{role,text,ts}]
    observations  TEXT,                  -- JSON: [{...观察, ts}]
    risk          TEXT,                  -- JSON: {level,reasons[],signals{}}
    metadata      TEXT,                  -- JSON: {duration_sec,channel,models}
    created_ts    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_video_calls_enterprise ON video_calls(enterprise_id, created_ts);
```

单表 + JSON 列，一个聚焦的存储单元；将来需按 anomalies 查询再拆子表。

## 组件

1. **`ui/video_calls.py`**（新）— 仿 `enterprise.py` 的持久化层：
   - `start_call(enterprise_id, user_id) -> call_id`
   - `complete_call(call_id, enterprise_id, *, transcript, observations, risk, metadata)`
   - `load_call(call_id, enterprise_id) -> dict | None`
   - `list_calls(enterprise_id) -> list[dict]`
   - 全部按 `enterprise_id` 隔离，跨企业读不到（与 `messages` 一致）。

2. **`ui/server.py`** — 3 个鉴权端点（`current_context()` 取企业）：
   - `POST /api/video-call/start` → `{call_id}`
   - `POST /api/video-call/{id}/complete` → 校验归属后写入
   - `GET /api/video-call` → 列表（验证/调试）

3. **`realtime/doubao-realtime-proxy.mjs`** — 新增 `POST /api/risk-summary`：规则聚合 + ARK 总结，best-effort（失败返回带 null 总结的纯规则结果）。

4. **`ui/static/chat.js`** — `videoCall` 状态加 `callId/transcriptLog/observationsLog`；`openVideoCall` 接通调 `/start`；`onAiText/onUserText/videoSendText/videoSampleFrame` 累积日志；`closeVideoCall` 两步提交；加 `beforeunload` sendBeacon 兜底。

## 错误处理

- 落库失败**不影响通话体验**（通话已结束）：客户端记 console、静默；服务端严格校验企业归属，越权访问返回 404。
- `complete` 对已 `completed` 的 call 幂等（覆盖写）。

## 测试

`tests/test_video_calls.py`（沿用现有 unittest + 临时 DATA_DIR 风格）：
- start → complete → load 往返。
- 企业隔离：A 企业的 call_id，B 企业 `load_call`/`complete_call` 取不到、不可写。
- `list_calls` 仅返回本企业、按时间倒序。
- `complete` 幂等覆盖。
