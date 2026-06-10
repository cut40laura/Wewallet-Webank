# 设计：长程业务一致性反欺诈（视频通话）

> 日期：2026-06-10
> 状态：待评审（已吸收 Codex 第一轮审查的 8 条意见，v2）
> 涉及：`ui/static/chat.js`、`realtime/doubao-realtime-proxy.mjs`、`ui/server.py`（reason 分类）

## 1. 背景与问题

视频通话 AI 客户经理已有的反欺诈能力：

- 口述 vs **历史档案** 比对（`/api/contradiction-check`，只带最近 6 轮上下文）。
- 口述场景 vs 画面场景 本地确定性比对 + 升级状态机（`videoCheckSceneMismatch` / `videoCall.sceneDeception`）。
- 提示词层"先质疑不附和"。

**本设计要补的缺口——长程"业务自我变卦"抓不到。** 用户在同一通通话里对自己报过的业务/借贷事实前后变卦，典型：

- 借款金额 `500万 → 1000万`；
- 用途分配 `厂房 300→800 / 设备 100→200`（**仅当用户明确改了某项**，见 §4.2 抽取规则）；
- 自报行业自我变卦：先说"我做美甲的"、后说"我们是半导体公司"。

这些矛盾可能相隔 10、20、30 轮。现有检测是"口述 vs 档案"且仅带最近 6 轮，**隔 20 轮的自我变卦完全在窗口外**。

**明确划出范围外（见 §2 非目标）：** "美业工作室声称与英伟达合作"这类——经营主体与所声称业务/合作方是否**合理**——不是"前后变卦"，而是"业务合理性 / 交易背景异常"，需要行业知识、企业档案或材料核验规则才能判定，**本设计不处理**，仅在此标注为后续独立议题。本设计的 `industry`/`partners` 字段只负责"用户在本通里**自己**前后说法是否变了"。

## 2. 目标

- **长程业务一致性**：贯穿整通通话**有状态地**追踪结构化业务主张；抽取为 best-effort（依赖 LLM），但**保存、比对触发、升级、落档是确定性的**。任意轮数间隔的自我变卦都进入检测（不再受 6 轮窗口限制）。
- **情绪免疫（仅业务/借贷）**：业务话题下，情绪不得导致 AI 撤回疑点、降低材料要求或松动审批口径；闲聊话题仍可顺着安抚、灵活。
- **审计痕迹**：每次业务主张/变更逐条留痕（不只最后值），随通话落档，供人工复核。

**非目标（YAGNI / 范围外）：**
- 不做正则本地数字抽取（抽取交给 LLM）。
- 不改动语音通话（voice）路径。
- 不做历史档案侧的结构化重建（档案比对仍走现有 `/api/contradiction-check`）。
- **不做"业务合理性 / 交易背景异常"判定**（如美业 vs 英伟达合作的可信度）——单列为后续议题。

## 3. 总体架构

复用既有"客户端有状态 + 服务端无状态抽取 + 升级状态机 + 矛盾落库"基建：

```
用户发言(ASR/打字)
  → 去抖(videoScheduleContradictionCheck，现有 1400ms)
  → 并行两路：
      ① 现有：/api/contradiction-check（口述 vs 档案）
      ② 新增：/api/business-claim-check（口述 vs 业务账本，自我一致性）
  → 命中矛盾(已是 field/stated/known/nudge 规范形)
        → videoHandleContradiction（现有：去重弹窗 + nudge + 落库）
        → 业务升级状态机 videoCall.businessIntegrity
  → 挂断 → businessLedger 快照 + businessClaimEvents + 业务矛盾并入 risk → /complete 落库
```

- **账本状态在客户端**（`videoCall.businessLedger`），贯穿整通；用**串行队列**保证按入队顺序、用最新账本逐句处理（§4.3）。
- **抽取/比对在服务端无状态**（`/api/business-claim-check`，放代理 `doubao-realtime-proxy.mjs`，紧邻 `/api/contradiction-check`）。
- 情绪免疫：提示词为第一道防线；账本抓到矛盾且检测到情绪施压时注入升级 nudge 为长程兜底（语音/文字两条注入路径不同，见 §4.6）。

## 4. 组件设计

### 4.1 业务主张账本 + 事件流水（客户端）

`ui/static/chat.js` 的 `videoCall` 新增：

```js
// 账本：每字段只保留"最新值"，用于快速比对
businessLedger: {
  loan_total:    null,  // { value: 500, unit: "万", raw: "借500万", ts }
  allocations:   {},    // { 厂房:{value:300,unit:"万",ts}, 设备:{...} }   仅出现过的用途
  industry:      null,  // { value: "美甲店", ts }   用户本通自报的行业
  partners:      [],    // [ { value: "英伟达", ts } ]   用户本通自报的合作方
  business_data: {}     // { 月流水:{value:15,unit:"万",ts}, 员工数:{value:5,ts} }
},
// 事件流水：逐条留痕，支撑"变过几次"的审计（点6）
businessClaimEvents: []  // [ { field, value, raw, ts, seq, event_type } ]
                         // event_type: "initial"(首次出现) | "update"(改了旧值) | "clarification"(口误澄清)
```

- `openVideoCall` 时把两者都重置（账本清空、events 清空）。
- 每次抽取接口返回后：按串行队列顺序处理（§4.3）；采纳则覆盖账本、并把本句涉及的每个业务主张 append 进 `businessClaimEvents`，用 `event_type` 区分首次出现 / 改值 / 澄清——只有 `event_type:"update"` 才算矛盾。
- 挂断时把账本最终快照 + events 一并落档（§4.7）。

> 金额统一在抽取侧归一化为 `{value:数字, unit:"万"|"元"}`（万→元换算见 §4.2），比对按归一化后的数值，避免"500万"vs"5000000元"被误判为变化。

### 4.2 抽取接口 `/api/business-claim-check`（服务端，无状态）

放在 `realtime/doubao-realtime-proxy.mjs`，仿照现有 `/api/contradiction-check`（ARK 文本模型，固定 JSON schema，**temperature=0**）。

**入参：**
```json
{ "ledger": { ...当前账本... }, "utterance": "本句用户口述", "recent": "近 6 轮文本", "seq": 7 }
```

**出参（contradictions 已是落库管线的规范形，点1）：**
```json
{
  "seq": 7,
  "is_business": true,
  "emotional_pressure": false,
  "updated_ledger": { ...合并本句主张后的新账本（已归一化）... },
  "claim_events": [
    { "field": "loan_total", "value": 1000, "unit": "万", "raw": "要1000万", "event_type": "update" }
  ],
  "clarified": ["loan_total"],
  "contradictions": [
    {
      "field": "业务不一致·借款金额",
      "stated": "本次：1000万",
      "known": "此前：500万",
      "nudge": "您前面提到借500万，现在说的是1000万，差挺多，咱们得对一下具体需求……",
      "severity": "medium",
      "kind": "business_integrity"
    }
  ]
}
```

字段说明：
- `seq`：原样回传请求里的 `seq`，仅作日志/调试关联用途；正确性由客户端串行队列保证，不靠 seq 丢弃响应（§4.3）。
- `is_business`：本句是否业务/借贷相关。非业务则不进核验、不注入业务 nudge（闲聊路径不受影响）。
- `emotional_pressure`：本句是否带明显情绪施压（生气/委屈/感动等）。仅作辅助信号，**不作为唯一判据**——是否触发核验只取决于"账本是否实质变化"这一确定性条件。
- `updated_ledger`：把本句抽到的业务主张并入账本后的结果（已归一化）；本句未提及的字段**原样保留**，不清空。**账本的更新只来自 `claim_events`**——`claim_events` 为空（含 `is_business=false` 的情形）时，`updated_ledger` 必须等于入参 `ledger`，客户端也不改动本地账本。
- `claim_events`：本句涉及的业务主张逐条，每条带 `event_type:"initial"|"update"|"clarification"`，客户端 append 到 `businessClaimEvents`。只有 `event_type:"update"` 会产生 `contradictions`。
- `clarified`：用户对某字段做了口误澄清/明确收敛（如"我口误，就是500万"）的字段名 → 该字段停止升级（§4.4），但已落库矛盾保留。
- `contradictions`：与账本已有值**实质不同**的字段，**已转换成 `{field, stated, known, nudge, severity, kind}` 规范形**（`kind:"business_integrity"`），可直接进 `videoHandleContradiction`，不再需要客户端转换。`stated`=本次说法，`known`=此前说法。

**抽取规则（关键，避免误报，点4 & 点8）：**
- **`event_type` 判定**：字段首次出现 → `initial`（写入账本，**不算矛盾**）；与账本旧值不同 → `update`（**算矛盾**，含明确改值 500→1000、或明确移除/归零"工资不用了/全投厂房设备"）；用户对某字段口误澄清/收敛 → `clarification`（停止该字段升级，不算新矛盾）。
- **"未提及" ≠ 变化**：本句没说到某字段，**不产生该字段的 claim_event**，账本保留旧值。
- 字段白名单：只抽 `loan_total / allocations.* / industry / partners / business_data.*`，schema 外内容忽略。
- 金额单位归一化：万↔元统一为 `{value, unit}`；无法确定单位时标 `unit:null` 且**不**与已有值判矛盾（保守）。
- **失败保守**：ARK 报错、JSON 解析失败、schema 校验不过 → 返回 `is_business:false, contradictions:[], updated_ledger=入参 ledger 原样`（best-effort，不阻塞通话、不误报），与现有接口降级风格一致。

### 4.3 客户端接入（`videoRunBusinessCheck`）+ 串行队列

仿照现有 `videoRunContradictionCheck`，但**不依赖 `memoryText`**（无档案也要做自我一致性）。

**为什么必须串行而非 latest-wins（点2）**：业务检测的正确性依赖"请求用的是最新账本"。若并发——第二句的请求在第一句返回前派发，它带的是**旧账本快照**，就识别不出 `500万→1000万`；而 latest-wins 又会丢掉第一句的有效主张。因此**不能并发、也不能简单 latest-wins**。

**串行队列设计**：
- `videoCall.businessQueue = []`（待处理 utterance）、`videoCall.businessBusy = false`（是否有请求在途）。
- `videoScheduleContradictionCheck` 去抖回调里，把本轮 utterance **入队**，触发 `videoDrainBusinessQueue()`。
- `videoDrainBusinessQueue`：若 `businessBusy` 则直接返回（在途请求完成后会自驱继续）；否则取队首，用**当前最新** `videoCall.businessLedger` 组装请求并发出，置 `businessBusy=true`。
- 响应返回：先用最新账本采纳结果（见下），再 `businessBusy=false`、若队列非空则继续 `videoDrainBusinessQueue()`。
- 这样每条 utterance **按入队顺序、用处理时刻的最新账本** 依次处理，既不乱序也不丢主张。`seq` 仅作日志/调试用途，不再承担正确性。
- 队列上限（如 8 条）防异常堆积；超限丢弃最旧的非业务噪声。

**采纳规则**：
- `is_business=false` **或** `claim_events` 为空：**不改动本地账本**（§4.2 已约束 `updated_ledger==ledger`），不触发核验/nudge。
- 否则：覆盖 `businessLedger`、append `claim_events` 到 `businessClaimEvents`、`contradictions`（仅来自 `event_type:"update"`）逐条进业务状态机（§4.4）；`clarified` 字段做去升级处理。

### 4.4 业务升级状态机

`videoCall.businessIntegrity = { state, hits, flaggedLogged, lastHitAt, outstanding: [] }`，模式同 `sceneDeception`：

| hits | state | AI 行为（经 nudge 引导） |
|---|---|---|
| 1 | `challenged` | 共情一句 + 温和指出出入，请其确认/解释（走现有 `videoHandleContradiction`：弹窗+落库+nudge） |
| 2 | `evidence_required` | 坚定要材料证明，不让步（绕开去重直接注入升级 nudge） |
| ≥3 / 持续回避 | `flagged` | 标记"业务前后不一致·高风险"，落档（distinct field 不被去重），AI 后续更谨慎；只落一次 |

- **去升级/停追**：用"未澄清矛盾字段集合" `outstanding`。每条新业务矛盾把其 `field` 加入 `outstanding` 并 `hits += 1` 推进状态；接口返回 `clarified` 的字段从 `outstanding` 移除并让 AI 停止当场纠缠该字段。当 `outstanding` 清空且尚未 `flagged` 时，`state` 回落 `none`、`hits` 归零。**已落库矛盾始终保留**（落档审计不抹）。
- **一旦 flagged**：保留、停止反复纠缠（`flaggedLogged` 守卫），`clarified` 不再使其回落。
- `hits` 升级计数按整通累计；矛盾按字段（loan_total / allocations.厂房 / industry…）独立记录与去重。

> 与场景欺骗状态机相互独立，各记各的；两者的 flagged 都通过 `videoMergeContradictions` 抬升 risk 等级（reason 按 kind 区分，§4.7）。

### 4.5 情绪免疫（提示词）

`realtime/doubao-realtime-proxy.mjs` 的 `VIDEO_SYSTEM_ROLE`（实时）与 `VIDEO_CHAT_SYSTEM_PROMPT`（文字兜底）各加一条规则：

> 【话题分流·业务不让步】先分清话题：闲聊、情绪宣泄可以顺着安抚、灵活给台阶。但只要涉及业务或借贷（专业知识、金额、用途、经营、合作方、材料），就进入"核验优先"：用户表现生气/委屈/感动等情绪时，先共情一句，但绝不因此撤回已指出的疑点、不降低材料要求、不松动审批口径，坚持把前后不一致摆出来核对、请其提供材料证明。

### 4.6 情绪免疫（升级 nudge）——语音 / 文字两条注入路径（点3）

业务矛盾命中且（`emotional_pressure` 或状态升级）时，按状态生成升级提示，但**两个通道注入方式不同**：

- **实时语音通道**：经 `videoCall.client.sendContext(...)` 注入实时 WebSocket 上下文。代理的现有行为是：**AI 正在播报时缓存到该句播完(TTSEnded)再喂；空闲时立即静默喂入并吞掉该轮播报**——因此 nudge 不会打断正在播的语音，只 steer 下一句。
- **文字通道（`/api/video-chat`）**：`sendContext` 对它**无效**（它是另起 HTTP 流式请求）。因此 `videoSendText` 必须**先 await 业务检测**，若返回 business 矛盾，把升级话术作为一条 `parts` 拼进 `/api/video-chat` 的 messages（与现有把"视觉摘要/知识库"拼进 messages 同理），本次文字回复才会体现。代价是文字回复前多一次抽取往返延迟——贷款审批场景可接受。

升级话术（两通道共用文案，按状态分级）：
- `challenged`：`（风控提示：用户业务说法前后不一致——<field>：<known> → <stated>。共情一句，但务必自然指出这处出入，请其确认或解释。）`
- `evidence_required`：`（风控升级：用户仍变卦/回避且在用情绪施压。这是贷款审批，不能松动。共情但坚定地请其提供能对上的材料证明。）`
- `flagged`：`（风控提示：多次变卦无法自圆其说，已标记高风险，后续更谨慎；口吻仍客气、不指控。）`

### 4.7 落档（审计痕迹）+ high reason 分类（点5、点6）

- 业务矛盾复用 `contradictionsLog → risk.contradictions → /complete` 链路，已是规范 `field/stated/known/nudge` 形，带 `kind:"business_integrity"`。
- **high reason 分类（点5）**：现有 `videoMergeContradictions` 的 high reason 硬编码为"疑似画面欺骗"。需改为**按 `kind` 生成 reason**：场景欺骗给画面文案、`business_integrity` 给"通话中检测到业务说法前后不一致（金额/用途/行业等多次变卦，经核对与取证仍无法对上）"。建议让每条 flagged contradiction 自带 `reason`，`videoMergeContradictions` 收集去重后写入 `risk.reasons`，而非写死单一文案。
- **审计快照（点6）**：挂断时写入
  - `risk.business_ledger`：账本最终快照（最后值）；
  - `risk.business_claim_events`：完整事件流水（每条 `field/value/raw/ts/seq/event_type`），人工复核可据此一眼看清"报过哪些数、变过几次"（数 `event_type:"update"` 即变更次数）。

## 5. 数据流（端到端举例）

1. 第 3 轮用户："想借500万，300万厂房、100万设备、100万工资。" → 抽取写入 `loan_total=500万 / allocations={厂房:300,设备:100,工资:100}`；events 各记一条 `event_type:"initial"`（首次出现）；无矛盾。
2. AI 正常介绍流程。
3. 第 25 轮用户（装生气）："早说了要1000万！800万厂房、200万设备！你怎么还不懂！" → 对比账本：`loan_total 500→1000`、`厂房 300→800`、`设备 100→200` 三条 `event_type:"update"`；**工资本句没提 → 无 claim_event、不判矛盾、账本保留 100**（点4）。`is_business=true`、`emotional_pressure=true`，返回 3 条规范形 contradictions。
4. 业务状态机推进；`videoHandleContradiction` 弹"业务不一致"提示并落库；按通道注入"共情但坚持要材料"的升级 nudge（语音 sendContext / 文字拼进 messages）。
5. AI 下一句：共情一句 + 明确指出"前面是500万、现在1000万，差挺大"，请其提供材料证明，不因生气松动。
6. 挂断：`risk.business_ledger`（最后值）+ `risk.business_claim_events`（含三次变卦）+ 业务矛盾并入 risk；flagged 时 `risk.level=high` 且 reason 为业务不一致文案。

## 6. 已知限制（如实记录）

- **抽取是 best-effort，不是确定性**：字段抽取/单位识别依赖 ARK 文本模型，可能偶发漏抽/误抽。确定性体现在"保存、比对、升级、落档"。已用 temperature=0 + 字段白名单 + 单位归一化 + 失败保守返回来收紧（§4.2）。
- 实时模型边听边答，nudge 有去抖+接口延迟，可能在模型已软回应后才到。**第一道防线是提示词**，nudge 是长程确定性兜底（steer 下一轮）。
- 情绪检测为辅助信号，触发与否取决于"账本是否实质变化"。
- "业务合理性/交易背景异常"（行业-合作方可信度）不在本设计范围（§2）。

## 7. 测试计划

- **单元（纯函数，node 脚本）**：业务状态机推进/`outstanding` 去升级/`flagged` 只落一次（仿 `sceneDeception` 已有单测）；账本合并与"未提及≠矛盾"、单位归一化、字段级矛盾判定。
- **串行队列**：连续两句业务发言（第二句在第一句返回前入队），校验第二句用的是第一句更新后的账本（能识别 500→1000），且两句的主张都不丢、按序处理。
- **接口（mock LLM 或固定样例）**：给定 ledger+utterance，校验出参 schema、`contradictions` 为规范形、失败时保守返回。
- **落库链路**：构造一条 `kind:"business_integrity"` flagged 矛盾，校验 `videoMergeContradictions` 生成业务 reason（不是画面欺骗文案）、`risk.level=high`、`risk.business_claim_events` 落库。
- **端到端（人工）**："500万→（隔 20+ 轮）→1000万 + 装生气"用例：①弹业务不一致并升级、②AI 共情但坚持要材料不松动、③挂断后 risk.level=high 且审计快照含变卦痕迹。

## 8. 涉及文件清单

- `ui/static/chat.js`：
  - `videoCall.businessLedger` / `businessClaimEvents` / `businessIntegrity` / `businessQueue` / `businessBusy` 字段与 `openVideoCall` 重置；
  - `videoRunBusinessCheck` + `videoDrainBusinessQueue`（串行队列，用最新账本逐句处理）；`videoScheduleContradictionCheck` 接入；
  - 业务升级状态机；
  - `videoSendText` 文字通道：await 业务检测并把升级话术拼进 `/api/video-chat` messages（§4.6）；
  - `videoMergeContradictions`：high reason 按 `kind` 生成（§4.7）；
  - 落档处写入 `risk.business_ledger` 与 `risk.business_claim_events`。
- `realtime/doubao-realtime-proxy.mjs`：新增 `/api/business-claim-check`（temperature=0、字段白名单、归一化、失败保守）；`VIDEO_SYSTEM_ROLE` 与 `VIDEO_CHAT_SYSTEM_PROMPT` 加"业务不让步"规则。
- `ui/server.py`：`_verifications_from_risk` 已读 `field/stated/known`，业务矛盾规范形天然兼容；如需按 `kind` 区分待核验文案，可在此做小适配（可选）。
