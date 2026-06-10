# 设计：长程业务一致性反欺诈（视频通话）

> 日期：2026-06-10
> 状态：待评审（用户将交由 Codex 复核后执行）
> 涉及：`ui/static/chat.js`、`realtime/doubao-realtime-proxy.mjs`

## 1. 背景与问题

视频通话 AI 客户经理已有的反欺诈能力：

- 口述 vs **历史档案** 比对（`/api/contradiction-check`，只带最近 6 轮上下文）。
- 口述场景 vs 画面场景 本地确定性比对 + 升级状态机（`videoCheckSceneMismatch` / `videoCall.sceneDeception`）。
- 提示词层"先质疑不附和"。

**两个未覆盖的缺口：**

1. **长程业务自我变卦抓不到。** 用户对业务/借贷事实前后变卦——典型：借款金额 `500万→1000万`、用途分配 `厂房300→800 / 设备100→200 / 工资100→0`、美业工作室却声称与英伟达等不相关企业合作。这种矛盾可能相隔 10、20、30 轮。现有检测是"口述 vs 档案"且仅带最近 6 轮，**隔 20 轮的自我变卦完全在窗口外**。

2. **情绪施压会让 AI 在业务问题上松动。** 用户装生气/委屈/感动施压时，现有提示词强调"不指控、给台阶、别让对方紧张"，可能被读成"软化"。但贷款审批中，业务/借贷相关的疑点不能因情绪而撤回。

## 2. 目标

- **长程业务一致性**：贯穿整通通话追踪结构化业务主张，任意轮数间隔的变卦都能确定性抓到。
- **情绪免疫（仅业务/借贷）**：业务话题下，情绪不得导致 AI 撤回疑点、降低材料要求或松动审批口径；闲聊话题仍可顺着安抚、灵活。
- **审计痕迹**：变卦与最终业务主张快照随通话落档，供人工复核。

**非目标（YAGNI）：** 不做正则本地数字抽取；不改动语音通话（voice）路径；不做历史档案侧的结构化重建（档案比对仍走现有接口）。

## 3. 总体架构

复用既有"客户端有状态 + 服务端无状态抽取 + 升级状态机 + 矛盾落库"基建：

```
用户发言(ASR/打字)
  → 去抖(videoScheduleContradictionCheck，现有 1400ms)
  → 并行两路：
      ① 现有：/api/contradiction-check（口述 vs 档案）
      ② 新增：/api/business-claim-check（口述 vs 业务账本，自我一致性）
  → 命中矛盾 → videoHandleContradiction（现有：去重弹窗 + nudge + 落库）
            → 业务升级状态机 videoCall.businessIntegrity
  → 挂断 → businessLedger 快照 + 业务矛盾并入 risk → /complete 落库
```

- **账本状态在客户端**（`videoCall.businessLedger`），贯穿整通。
- **抽取/比对在服务端无状态**（`/api/business-claim-check`，放代理 `doubao-realtime-proxy.mjs`，紧邻 `/api/contradiction-check`）。
- 情绪免疫：提示词为第一道防线；账本抓到矛盾且检测到情绪施压时注入升级 nudge 为长程兜底。

## 4. 组件设计

### 4.1 业务主张账本（客户端）

`ui/static/chat.js` 的 `videoCall` 新增字段：

```js
businessLedger: {
  loan_total:    null,  // { value: 500, unit: "万", raw: "借500万", ts }
  allocations:   {},    // { 厂房:{value:300,unit:"万",ts}, 设备:{...}, 工资:{...} }
  industry:      null,  // { value: "美业工作室", ts }  口述声称的经营/行业
  partners:      [],    // [ { value: "英伟达", ts }, ... ]
  business_data: {}     // { 月流水:{value:15,unit:"万",ts}, 员工数:{value:5,ts} ... }
}
```

- `openVideoCall` 时重置为空账本（与现有 `videoCall.*` 重置同处）。
- 每次抽取接口返回 `updated_ledger` 后整体覆盖本地账本。
- 挂断时把最终快照随通话落档。

### 4.2 抽取接口 `/api/business-claim-check`（服务端，无状态）

放在 `realtime/doubao-realtime-proxy.mjs`，仿照现有 `/api/contradiction-check`（ARK 文本模型，固定 JSON schema）。

**入参：**
```json
{ "ledger": { ...当前账本... }, "utterance": "本句用户口述", "recent": "近 6 轮文本" }
```

**出参：**
```json
{
  "is_business": true,
  "emotional_pressure": false,
  "updated_ledger": { ...合并本句主张后的新账本... },
  "clarified": ["loan_total"],
  "contradictions": [
    { "field": "loan_total", "old": "500万", "new": "1000万",
      "nudge": "您前面提到借500万，现在说的是1000万，差挺多，咱们得对一下具体需求……" }
  ]
}
```

字段说明：
- `is_business`：本句是否业务/借贷相关。用于情绪免疫门控（非业务则不进核验、不注入业务 nudge）。
- `emotional_pressure`：本句是否带明显情绪施压（生气/委屈/感动等）。
- `updated_ledger`：LLM 把本句抽到的业务主张并入账本后的结果；空字段保持 null/[]/{}。
- `clarified`：用户对某字段做了口误澄清/明确收敛（如"我口误，就是500万"）的字段名列表 → 该字段停止升级（但已记录的矛盾保留）。
- `contradictions`：本句新主张与账本已有值**实质不同**的字段（金额/分配/行业/合作方/经营数据）。每条带可用作 nudge 的自然话术。

**LLM 职责**：仅"抽取本句业务主张 + 与传入账本逐字段比对"，不依赖跨请求记忆，保证确定性可控。ARK 失败时返回空 `contradictions`（best-effort，不阻塞通话），与现有接口降级风格一致。

### 4.3 客户端接入（`videoRunBusinessCheck`）

仿照现有 `videoRunContradictionCheck`：

- 在 `videoScheduleContradictionCheck` 去抖回调里**并行**调用（不依赖 `memoryText`，无档案也要做自我一致性）。
- 拿到 `updated_ledger` 覆盖 `videoCall.businessLedger`。
- `contradictions` 逐条经业务状态机处理（见 4.4）。
- `is_business=false` 时：仍更新账本但不触发任何核验/nudge（让 AI 闲聊路径不受影响）。

### 4.4 业务升级状态机

`videoCall.businessIntegrity = { state, hits, flaggedLogged, lastHitAt, outstanding: [] }`，模式同 `sceneDeception`：

| hits | state | AI 行为（经 nudge 引导） |
|---|---|---|
| 1 | `challenged` | 共情一句 + 温和指出出入，请其确认/解释（走现有 `videoHandleContradiction` 管线：弹窗+落库+nudge） |
| 2 | `evidence_required` | 坚定要材料证明，不让步（绕开去重直接注入升级 nudge） |
| ≥3 / 持续回避 | `flagged` | 标记"业务前后不一致·高风险"，落档（distinct field 不被去重），AI 后续更谨慎；只落一次 |

- **去升级/停追**：用一个"未澄清矛盾字段集合" `outstanding` 配合状态机。每条新业务矛盾把其 `field` 加入 `outstanding` 并 `hits += 1` 推进状态；接口返回 `clarified` 的字段从 `outstanding` 移除并让 AI 停止当场纠缠该字段。当 `outstanding` 清空且尚未 `flagged` 时，`state` 回落 `none`、`hits` 归零。**已落库的矛盾记录始终保留**（落档审计不抹）。
- **一旦 flagged**：保留、停止反复纠缠（`flaggedLogged` 守卫），`clarified` 不再使其回落。
- `hits` 升级计数按整通累计；矛盾按字段（loan_total / allocations.厂房 / industry…）独立记录与去重。

> 与场景欺骗状态机相互独立，各记各的；两者的 flagged 都通过 `videoMergeContradictions` 抬升 risk 等级。

### 4.5 情绪免疫（提示词）

`realtime/doubao-realtime-proxy.mjs` 的 `VIDEO_SYSTEM_ROLE`（实时）与 `VIDEO_CHAT_SYSTEM_PROMPT`（文字兜底）各加一条规则：

> 【话题分流·业务不让步】先分清话题：闲聊、情绪宣泄可以顺着安抚、灵活给台阶。但只要涉及业务或借贷（专业知识、金额、用途、经营、合作方、材料），就进入"核验优先"：用户表现生气/委屈/感动等情绪时，先共情一句，但绝不因此撤回已指出的疑点、不降低材料要求、不松动审批口径，坚持把前后不一致摆出来核对、请其提供材料证明。

### 4.6 情绪免疫（升级 nudge）

接口返回 `emotional_pressure=true` 且命中业务矛盾时，按状态注入更强 context（经代理"句末再喂"，steer 下一句）：

- `challenged`：`（风控提示：用户业务说法前后不一致——<field> 从<old>变<new>。共情一句，但务必自然指出这处出入，请其确认或解释。）`
- `evidence_required`：`（风控升级：用户仍变卦/回避且在用情绪施压。这是贷款审批，不能松动。共情但坚定地请其提供能对上的材料证明。）`
- `flagged`：`（风控提示：多次变卦无法自圆其说，已标记高风险，后续更谨慎；口吻仍客气、不指控。）`

### 4.7 落档（审计痕迹）

- 业务矛盾复用 `contradictionsLog → risk.contradictions → /complete` 链路，`field` 命名如 `业务不一致·借款金额`。
- flagged 业务矛盾带 `severity:"high"` → 现有 `videoMergeContradictions` 自动把 `risk.level` 抬到 high 并加 reason。
- 挂断时把 `businessLedger` 最终快照写入 `risk.business_ledger`，供人工复核（一眼看清报过哪些数、变过几次）。

## 5. 数据流（端到端举例）

1. 第 3 轮用户："想借500万，300万厂房、100万设备、100万工资。" → 接口抽取，账本写入 `loan_total=500万 / allocations={厂房:300,设备:100,工资:100}`，无矛盾（首次）。
2. AI 正常介绍流程。
3. 第 25 轮用户（装生气）："早说了要1000万！800万厂房、200万设备！你怎么还不懂！" → 接口对比账本：`loan_total 500→1000`、`厂房 300→800`、`设备 100→200`、`工资 100→缺`，`is_business=true`、`emotional_pressure=true`，返回多条 contradictions。
4. 业务状态机推进；`videoHandleContradiction` 弹"业务不一致"提示并落库；注入"共情但坚持要材料"的升级 nudge。
5. AI 下一句：共情一句 + 明确指出"前面是500万、现在1000万，差挺大"，请其提供材料证明，不因生气松动。
6. 挂断：账本快照 + 业务矛盾并入 risk（level=high），落库。

## 6. 已知限制（如实记录）

- 实时模型自己边听边答，nudge 有去抖+接口延迟，可能在模型已软回应后才到。**第一道防线是提示词**，nudge 是长程确定性兜底（steer 下一轮）。代理已改为"句末再喂 context"，nudge 落在句子间隙、不打断。
- 抽取准确度依赖 ARK 文本模型，可能偶发漏抽/误抽；接口降级返回空矛盾，不阻塞通话。
- 情绪检测为辅助信号，不作为唯一判据；核验是否触发由"账本是否实质变化"这一确定性条件决定。

## 7. 测试计划

- **单元（纯函数，node 脚本）**：业务状态机推进/回落/只落库一次（仿 `sceneDeception` 已有单测）；账本合并与字段级矛盾判定。
- **接口（mock LLM 或固定样例）**：给定 ledger+utterance，校验 `updated_ledger`/`contradictions`/`is_business`/`emotional_pressure`/`clarified` 结构正确。
- **端到端（人工）**：构造"500万→（隔 20+ 轮）→1000万 + 装生气"用例，确认①弹业务不一致并升级、②AI 共情但坚持要材料不松动、③挂断后 risk.level=high 且 `risk.business_ledger` 含变卦痕迹。

## 8. 涉及文件清单

- `ui/static/chat.js`：`videoCall.businessLedger` / `businessIntegrity` 字段与重置；`videoRunBusinessCheck`；`videoScheduleContradictionCheck` 接入；业务状态机；落档处加 `risk.business_ledger`。
- `realtime/doubao-realtime-proxy.mjs`：新增 `/api/business-claim-check`；`VIDEO_SYSTEM_ROLE` 与 `VIDEO_CHAT_SYSTEM_PROMPT` 加"业务不让步"规则。
