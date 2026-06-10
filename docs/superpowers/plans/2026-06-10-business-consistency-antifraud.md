# 长程业务一致性反欺诈 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在视频通话里贯穿整通追踪用户的结构化业务主张（借款金额/用途分配/行业/合作方/经营数据），用确定性比对抓出隔多轮的自我变卦，并在业务话题下做情绪免疫。

**Architecture:** LLM 只做"抽取"（best-effort），**确定性 JS 做"比对/归一化/事件分类"**（可单测）。客户端维护账本 + 串行队列；矛盾走现有 `videoHandleContradiction` 弹窗/nudge/落库管线 + 新业务升级状态机；落档加审计快照。

**Tech Stack:** 原生 JS（无框架，浏览器 `<script>` + Node 双导出）、Node 内置 `node --test`、现有豆包 ARK 文本模型、`http.server`（Python，仅落库侧小改）。

参考规格：`docs/superpowers/specs/2026-06-10-business-consistency-antifraud-design.md`

---

## 文件结构

| 文件 | 职责 | 新建/修改 |
|---|---|---|
| `realtime/business-claims.mjs` | 纯函数：金额归一化 + `mergeAndDiff`（账本合并、事件分类、生成规范形矛盾） | 新建（`export` + 可被 node --test 导入） |
| `realtime/business-claims.test.mjs` | 上面的单测 | 新建 |
| `realtime/doubao-realtime-proxy.mjs` | 新增 `/api/business-claim-check` 端点（LLM 抽取 → 调 `mergeAndDiff`）；两处提示词加"业务不让步" | 修改 |
| `ui/static/business-ledger.js` | 纯函数：业务升级状态机（含 outstanding/clarified/flagged）；双导出（window + module.exports） | 新建 |
| `ui/static/business-ledger.test.mjs` | 状态机单测 | 新建 |
| `ui/static/chat.html` | 引入 `business-ledger.js` | 修改（加一行 script） |
| `ui/static/chat.js` | 账本/队列/状态字段、`videoEnqueueBusinessCheck`、`videoDrainBusinessQueue`、去抖/文字接入、`videoMergeContradictions` reason 分类、落档 | 修改 |

**数据形状（全程统一）**

LLM 抽取返回：
```js
{
  is_business: true,
  emotional_pressure: false,
  claims: {
    loan_total: { value: 1000, unit: "万", raw: "要1000万" },     // 或 null
    allocations: { "厂房": { value: 800, unit: "万", raw: "800万厂房" } },
    industry: { value: "半导体公司", raw: "我们是半导体的" },        // 或 null
    partners: [ { value: "英伟达", raw: "和英伟达合作" } ],
    business_data: { "月流水": { value: 15, unit: "万", raw: "月流水15万" } }
  },
  clarified: ["loan_total"]   // 用户口误澄清的字段
}
```

`mergeAndDiff(ledger, extracted, nowTs)` 返回：
```js
{
  updated_ledger,                                  // 账本（合并后）
  claim_events: [ { field, value, unit, raw, ts, event_type } ],  // initial|update|clarification
  contradictions: [ { field, stated, known, nudge, severity, kind } ]  // 仅 update 产生
}
```

---

## Task 1: 纯函数 `business-claims.mjs` — 金额归一化 + 合并比对

**Files:**
- Create: `realtime/business-claims.mjs`
- Test: `realtime/business-claims.test.mjs`

- [ ] **Step 1: Write the failing test**

Create `realtime/business-claims.test.mjs`:
```js
import { test } from "node:test";
import assert from "node:assert/strict";
import { normalizeAmount, mergeAndDiff } from "./business-claims.mjs";

test("normalizeAmount 万→元", () => {
  assert.equal(normalizeAmount(500, "万"), 5000000);
  assert.equal(normalizeAmount(5000000, "元"), 5000000);
  assert.equal(normalizeAmount(15, "万"), 150000);
  assert.equal(normalizeAmount(10, null), null); // 单位未知 → 不可比
});

test("首次出现 = initial，无矛盾", () => {
  const ledger = { loan_total: null, allocations: {}, industry: null, partners: [], business_data: {} };
  const extracted = { is_business: true, emotional_pressure: false,
    claims: { loan_total: { value: 500, unit: "万", raw: "借500万" }, allocations: {}, industry: null, partners: [], business_data: {} },
    clarified: [] };
  const r = mergeAndDiff(ledger, extracted, 100);
  assert.equal(r.contradictions.length, 0);
  assert.equal(r.claim_events.length, 1);
  assert.equal(r.claim_events[0].event_type, "initial");
  assert.equal(r.updated_ledger.loan_total.value, 500);
});

test("改值 = update，产生规范形矛盾", () => {
  const ledger = { loan_total: { value: 500, unit: "万", raw: "借500万", ts: 1 }, allocations: { "厂房": { value: 300, unit: "万", raw: "300万", ts: 1 } }, industry: null, partners: [], business_data: {} };
  const extracted = { is_business: true, emotional_pressure: true,
    claims: { loan_total: { value: 1000, unit: "万", raw: "要1000万" }, allocations: { "厂房": { value: 800, unit: "万", raw: "800万" } }, industry: null, partners: [], business_data: {} },
    clarified: [] };
  const r = mergeAndDiff(ledger, extracted, 200);
  const fields = r.contradictions.map(c => c.field).sort();
  assert.deepEqual(fields, ["业务不一致·借款金额", "业务不一致·用途·厂房"].sort());
  const loan = r.contradictions.find(c => c.field === "业务不一致·借款金额");
  assert.equal(loan.kind, "business_integrity");
  assert.match(loan.stated, /1000/);
  assert.match(loan.known, /500/);
  assert.ok(loan.nudge.length > 0);
});

test("未提及字段不产生 event、不判矛盾、账本保留", () => {
  const ledger = { loan_total: { value: 500, unit: "万", raw: "500万", ts: 1 }, allocations: { "工资": { value: 100, unit: "万", raw: "100万", ts: 1 } }, industry: null, partners: [], business_data: {} };
  const extracted = { is_business: true, emotional_pressure: false,
    claims: { loan_total: { value: 1000, unit: "万", raw: "1000万" }, allocations: {}, industry: null, partners: [], business_data: {} },
    clarified: [] };
  const r = mergeAndDiff(ledger, extracted, 300);
  assert.equal(r.updated_ledger.allocations["工资"].value, 100); // 保留
  assert.ok(!r.claim_events.some(e => e.field === "allocations.工资")); // 无 event
});

test("行业自我变卦 = update", () => {
  const ledger = { loan_total: null, allocations: {}, industry: { value: "美甲店", raw: "做美甲", ts: 1 }, partners: [], business_data: {} };
  const extracted = { is_business: true, emotional_pressure: false,
    claims: { loan_total: null, allocations: {}, industry: { value: "半导体公司", raw: "我们是半导体的" }, partners: [], business_data: {} }, clarified: [] };
  const r = mergeAndDiff(ledger, extracted, 400);
  assert.ok(r.contradictions.some(c => c.field === "业务不一致·经营行业"));
});

test("单位未知不判矛盾（保守）", () => {
  const ledger = { loan_total: { value: 500, unit: "万", raw: "500万", ts: 1 }, allocations: {}, industry: null, partners: [], business_data: {} };
  const extracted = { is_business: true, emotional_pressure: false,
    claims: { loan_total: { value: 1000, unit: null, raw: "一千" }, allocations: {}, industry: null, partners: [], business_data: {} }, clarified: [] };
  const r = mergeAndDiff(ledger, extracted, 500);
  assert.equal(r.contradictions.length, 0); // 不可比 → 不判
});

test("partners 追加记录但不产生矛盾(v1)", () => {
  const ledger = { loan_total: null, allocations: {}, industry: null, partners: [{ value: "三星", raw: "三星", ts: 1 }], business_data: {} };
  const extracted = { is_business: true, emotional_pressure: false,
    claims: { loan_total: null, allocations: {}, industry: null, partners: [{ value: "英伟达", raw: "英伟达" }], business_data: {} }, clarified: [] };
  const r = mergeAndDiff(ledger, extracted, 600);
  assert.equal(r.contradictions.length, 0);
  assert.ok(r.updated_ledger.partners.some(p => p.value === "英伟达"));
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test realtime/business-claims.test.mjs`
Expected: FAIL（`Cannot find module './business-claims.mjs'`）

- [ ] **Step 3: Write minimal implementation**

Create `realtime/business-claims.mjs`:
```js
// 业务主张：金额归一化 + 账本合并/比对（确定性，纯函数，无 IO）。
// LLM 只负责抽取 claims；这里负责归一化、事件分类、生成规范形矛盾。

const FIELD_LABEL = {
  loan_total: "借款金额",
  industry: "经营行业",
};
function allocLabel(name) { return `用途·${name}`; }
function bizLabel(name) { return name; }

// 万→元归一化；单位未知返回 null（表示不可比，调用方保守不判矛盾）。
export function normalizeAmount(value, unit) {
  if (typeof value !== "number" || Number.isNaN(value)) return null;
  if (unit === "万") return Math.round(value * 10000);
  if (unit === "元") return Math.round(value);
  return null;
}

function emptyLedger() {
  return { loan_total: null, allocations: {}, industry: null, partners: [], business_data: {} };
}

// 比较两个金额型 claim（{value,unit}）是否"实质不同"。任一不可比 → 视为"无法判定"，返回 null。
function amountDiffers(a, b) {
  const na = normalizeAmount(a.value, a.unit);
  const nb = normalizeAmount(b.value, b.unit);
  if (na === null || nb === null) return null;
  return na !== nb;
}

function mkContradiction(field, stated, known, nudge) {
  return { field: `业务不一致·${field}`, stated: `本次：${stated}`, known: `此前：${known}`,
    nudge, severity: "medium", kind: "business_integrity" };
}

// 单值金额字段（loan_total）的合并比对
function mergeAmountField(ledgerVal, claim, label, ts, events, contradictions) {
  if (!claim) return ledgerVal;            // 本句未提及 → 保留
  const next = { value: claim.value, unit: claim.unit, raw: claim.raw, ts };
  if (!ledgerVal) {
    events.push({ field: label === "借款金额" ? "loan_total" : label, value: claim.value, unit: claim.unit, raw: claim.raw, ts, event_type: "initial" });
    return next;
  }
  const differs = amountDiffers(ledgerVal, claim);
  if (differs === true) {
    events.push({ field: "loan_total", value: claim.value, unit: claim.unit, raw: claim.raw, ts, event_type: "update" });
    contradictions.push(mkContradiction(label, claim.raw || `${claim.value}${claim.unit || ""}`,
      ledgerVal.raw || `${ledgerVal.value}${ledgerVal.unit || ""}`,
      `您前面提到${label}是${ledgerVal.raw || ledgerVal.value + (ledgerVal.unit||"")}，现在说的是${claim.raw || claim.value + (claim.unit||"")}，差挺多，咱们得对一下具体情况，方便的话提供材料核对下。`));
    return next;
  }
  return ledgerVal; // 相同或不可比 → 保留旧值，不判
}

export function mergeAndDiff(ledger, extracted, nowTs) {
  const ts = typeof nowTs === "number" ? nowTs : Date.now() / 1000;
  const base = ledger && typeof ledger === "object" ? ledger : emptyLedger();
  const updated = {
    loan_total: base.loan_total || null,
    allocations: { ...(base.allocations || {}) },
    industry: base.industry || null,
    partners: [...(base.partners || [])],
    business_data: { ...(base.business_data || {}) },
  };
  const events = [];
  const contradictions = [];
  const claims = (extracted && extracted.claims) || {};

  // loan_total
  updated.loan_total = mergeAmountField(updated.loan_total, claims.loan_total, "借款金额", ts, events, contradictions);

  // allocations.* （逐用途，金额型）
  for (const [name, claim] of Object.entries(claims.allocations || {})) {
    const prev = updated.allocations[name] || null;
    if (!prev) {
      updated.allocations[name] = { value: claim.value, unit: claim.unit, raw: claim.raw, ts };
      events.push({ field: `allocations.${name}`, value: claim.value, unit: claim.unit, raw: claim.raw, ts, event_type: "initial" });
      continue;
    }
    const differs = amountDiffers(prev, claim);
    if (differs === true) {
      updated.allocations[name] = { value: claim.value, unit: claim.unit, raw: claim.raw, ts };
      events.push({ field: `allocations.${name}`, value: claim.value, unit: claim.unit, raw: claim.raw, ts, event_type: "update" });
      contradictions.push(mkContradiction(allocLabel(name), claim.raw || `${claim.value}${claim.unit||""}`,
        prev.raw || `${prev.value}${prev.unit||""}`,
        `${name}这块您前面说${prev.raw || prev.value + (prev.unit||"")}，现在是${claim.raw || claim.value + (claim.unit||"")}，对不太上，咱们核对下，麻烦提供相关材料。`));
    }
  }

  // industry（单值字符串，自我变卦）
  if (claims.industry) {
    const prev = updated.industry;
    if (!prev) {
      updated.industry = { value: claims.industry.value, raw: claims.industry.raw, ts };
      events.push({ field: "industry", value: claims.industry.value, raw: claims.industry.raw, ts, event_type: "initial" });
    } else if (String(prev.value).trim() !== String(claims.industry.value).trim()) {
      events.push({ field: "industry", value: claims.industry.value, raw: claims.industry.raw, ts, event_type: "update" });
      contradictions.push(mkContradiction("经营行业", claims.industry.value, prev.value,
        `您前面说是做${prev.value}的，现在说是${claims.industry.value}，这出入挺大，咱们核对下经营主体，麻烦出示下营业执照或相关材料。`));
      updated.industry = { value: claims.industry.value, raw: claims.industry.raw, ts };
    }
  }

  // partners（v1：追加记录，不判矛盾）
  for (const p of claims.partners || []) {
    if (!updated.partners.some((x) => String(x.value).trim() === String(p.value).trim())) {
      updated.partners.push({ value: p.value, raw: p.raw, ts });
      events.push({ field: "partners", value: p.value, raw: p.raw, ts, event_type: "initial" });
    }
  }

  // business_data.*（金额/数值型，比对同 allocations）
  for (const [name, claim] of Object.entries(claims.business_data || {})) {
    const prev = updated.business_data[name] || null;
    if (!prev) {
      updated.business_data[name] = { value: claim.value, unit: claim.unit, raw: claim.raw, ts };
      events.push({ field: `business_data.${name}`, value: claim.value, unit: claim.unit, raw: claim.raw, ts, event_type: "initial" });
      continue;
    }
    const differs = amountDiffers(prev, claim);
    if (differs === true) {
      updated.business_data[name] = { value: claim.value, unit: claim.unit, raw: claim.raw, ts };
      events.push({ field: `business_data.${name}`, value: claim.value, unit: claim.unit, raw: claim.raw, ts, event_type: "update" });
      contradictions.push(mkContradiction(bizLabel(name), claim.raw || `${claim.value}${claim.unit||""}`,
        prev.raw || `${prev.value}${prev.unit||""}`,
        `${name}您前面报的是${prev.raw || prev.value + (prev.unit||"")}，现在是${claim.raw || claim.value + (claim.unit||"")}，咱们对一下，方便的话提供材料。`));
    }
  }

  return { updated_ledger: updated, claim_events: events, contradictions };
}

export { emptyLedger };
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test realtime/business-claims.test.mjs`
Expected: PASS（7 个 test 全绿）

- [ ] **Step 5: Commit**

```bash
git add realtime/business-claims.mjs realtime/business-claims.test.mjs
git commit -m "feat(antifraud): deterministic business-claim merge/diff with unit normalization"
```

---

## Task 2: 代理新增 `/api/business-claim-check` 端点

**Files:**
- Modify: `realtime/doubao-realtime-proxy.mjs`（在 `/api/contradiction-check` 端点附近，约 line 111 路由处 + line 620 区块）

- [ ] **Step 1: 在路由分发处注册新端点**

在 `doubao-realtime-proxy.mjs` 现有路由块（`if (req.method === "POST" && url.pathname === "/api/contradiction-check")` 同级）后追加：
```js
  if (req.method === "POST" && url.pathname === "/api/business-claim-check") {
    return handleBusinessClaimCheck(req, res);
  }
```

- [ ] **Step 2: 顶部引入纯函数模块**

在文件顶部 import 区（ES module）加：
```js
import { mergeAndDiff, emptyLedger } from "./business-claims.mjs";
```
（确认文件是 ESM：`package.json` 有 `"type":"module"`，已是。）

- [ ] **Step 3: 实现端点处理器（仿 `/api/contradiction-check` 的 ARK 调用风格）**

在 `// ============ 视频通话·实时矛盾检测 /api/contradiction-check` 区块之后追加：
```js
// ============ 视频通话·业务主张抽取 /api/business-claim-check（ARK 抽取 → 确定性比对）============
const BUSINESS_EXTRACT_PROMPT = `你是贷款尽调里的"业务主张抽取器"。只抽取用户这句话里**明确说出**的业务/借贷事实，绝不猜测、不补全。严格输出 JSON：
{"is_business":true/false,            // 本句是否与业务或借贷相关（金额/用途/经营/行业/合作/材料）
"emotional_pressure":true/false,      // 本句是否带明显情绪施压（生气/委屈/感动/催促）
"claims":{
  "loan_total":{"value":数字,"unit":"万"|"元","raw":"原话片段"}|null,   // 借款总额，没提就 null
  "allocations":{"用途名":{"value":数字,"unit":"万"|"元","raw":"原话"}},  // 如 厂房/设备/工资，没提就空对象
  "industry":{"value":"行业/经营内容","raw":"原话"}|null,                // 用户自报的行业，没提就 null
  "partners":[{"value":"合作方名","raw":"原话"}],                        // 没提就空数组
  "business_data":{"指标名":{"value":数字,"unit":"万"|"元","raw":"原话"}} // 如 月流水/员工数，没提就空对象
},
"clarified":["字段名"]                 // 用户明确口误澄清/收敛的字段（如"我口误就是500万"→["loan_total"]），没有就空数组
}
规则：本句没明确说的字段一律给 null/空，绝不从历史或常识补。数字单位拿不准时 unit 给 null。`;

async function handleBusinessClaimCheck(req, res) {
  let body;
  try { body = await readJsonBody(req); } catch { return sendJson(res, 400, { error: "bad json" }); }
  const ledger = (body && body.ledger) || emptyLedger();
  const utterance = String((body && body.utterance) || "").trim();
  const recent = String((body && body.recent) || "");
  const seq = body && body.seq;
  // 失败/无内容一律保守返回：不改账本、无矛盾。
  const safe = (extra = {}) => sendJson(res, 200, { seq, is_business: false, emotional_pressure: false,
    updated_ledger: ledger, claim_events: [], contradictions: [], clarified: [], ...extra });
  if (!utterance) return safe();

  let extracted;
  try {
    const raw = await arkChatJson(BUSINESS_EXTRACT_PROMPT,
      `近况：\n${recent}\n\n用户这句：${utterance}`); // arkChatJson: 复用现有 ARK 调用助手（见 Step 4）
    extracted = JSON.parse(raw);
  } catch (e) {
    return safe(); // ARK 失败/解析失败 → 保守
  }
  if (!extracted || extracted.is_business !== true) return safe();

  const { updated_ledger, claim_events, contradictions } = mergeAndDiff(ledger, extracted, Date.now() / 1000);
  return sendJson(res, 200, {
    seq,
    is_business: true,
    emotional_pressure: extracted.emotional_pressure === true,
    updated_ledger,
    claim_events,
    contradictions,
    clarified: Array.isArray(extracted.clarified) ? extracted.clarified : [],
  });
}
```

- [ ] **Step 4: 复用/抽出 ARK 文本调用助手**

检查 `/api/contradiction-check` 里调用 ARK 的代码：若已有可复用的"发 prompt+user、拿 JSON 字符串"函数，直接用其名替换上面的 `arkChatJson`。若没有，照其实现抽出一个：
```js
// 发一次 ARK 文本对话，temperature=0，返回 assistant 文本（可能含 JSON）。失败抛错。
async function arkChatJson(systemPrompt, userText) {
  const cfg = resolveVisionProvider(); // 现有：解析 ARK/QWEN 凭证
  if (!cfg || cfg.provider !== "ark") throw new Error("no ark");
  const resp = await fetch(`${cfg.baseUrl}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${cfg.apiKey}` },
    body: JSON.stringify({
      model: process.env.ARK_TEXT_MODEL || cfg.model,
      temperature: 0,
      messages: [ { role: "system", content: systemPrompt }, { role: "user", content: userText } ],
    }),
  });
  if (!resp.ok) throw new Error(`ark ${resp.status}`);
  const data = await resp.json();
  let text = data.choices?.[0]?.message?.content || "";
  const m = text.match(/\{[\s\S]*\}/); // 容错：抽出第一个 JSON 块
  return m ? m[0] : text;
}
```
> 注意：如果现有 `/api/contradiction-check` 已有同等函数（如 `arkText`/`callArk`），**用现有的，别新增重复**（DRY）。确认 `readJsonBody`/`sendJson` 是现有助手名；若名字不同，按现有命名替换。

- [ ] **Step 5: 语法检查 + 手测端点**

```bash
node --check realtime/doubao-realtime-proxy.mjs
# 重启代理
lsof -nP -iTCP:8870 -sTCP:LISTEN -t | xargs -r kill; sleep 1
node realtime/doubao-realtime-proxy.mjs > /tmp/rtc.log 2>&1 &
sleep 2
curl -s -X POST http://127.0.0.1:8870/api/business-claim-check -H 'Content-Type: application/json' \
  -d '{"ledger":{"loan_total":{"value":500,"unit":"万","raw":"500万","ts":1},"allocations":{},"industry":null,"partners":[],"business_data":{}},"utterance":"其实我要借1000万","recent":"","seq":1}'
```
Expected: 返回 JSON，`contradictions` 含 `业务不一致·借款金额`（若 ARK 凭证可用）；ARK 不可用时保守返回空（`is_business:false`）。

- [ ] **Step 6: Commit**

```bash
git add realtime/doubao-realtime-proxy.mjs
git commit -m "feat(antifraud): add /api/business-claim-check endpoint (ARK extract + deterministic diff)"
```

---

## Task 3: 提示词加"业务不让步"（情绪免疫）

**Files:**
- Modify: `realtime/doubao-realtime-proxy.mjs`（`VIDEO_SYSTEM_ROLE` 约 line 31；`VIDEO_CHAT_SYSTEM_PROMPT` 约 line 387）

- [ ] **Step 1: 给 `VIDEO_SYSTEM_ROLE` 追加规则**

在 `VIDEO_SYSTEM_ROLE` 末尾（`【边界】…` 之前）追加一段字符串拼接：
```js
  "【话题分流·业务不让步】先分清话题：闲聊、情绪宣泄可以顺着安抚、灵活给台阶。但只要涉及业务或借贷（专业知识、金额、用途、经营、合作方、材料），就进入"核验优先"：用户表现生气/委屈/感动等情绪时，先共情一句，但绝不因此撤回已指出的疑点、不降低材料要求、不松动审批口径，坚持把前后不一致摆出来核对、请其提供材料证明。" +
```

- [ ] **Step 2: 给 `VIDEO_CHAT_SYSTEM_PROMPT` 追加同义规则**

在 `VIDEO_CHAT_SYSTEM_PROMPT` 数组里（`【边界】…` 之前）插入一条：
```js
  "【话题分流·业务不让步】闲聊、情绪宣泄可以顺着安抚、灵活给台阶；但只要涉及业务或借贷（专业知识、金额、用途、经营、合作方、材料），就进入核验优先：用户生气/委屈/感动施压时，先共情一句，但绝不撤回已指出的疑点、不降低材料要求、不松动审批口径，坚持指出前后不一致并请其提供材料证明。",
```

- [ ] **Step 3: 语法检查 + 重启 + Commit**

```bash
node --check realtime/doubao-realtime-proxy.mjs
lsof -nP -iTCP:8870 -sTCP:LISTEN -t | xargs -r kill; sleep 1; node realtime/doubao-realtime-proxy.mjs > /tmp/rtc.log 2>&1 &
git add realtime/doubao-realtime-proxy.mjs
git commit -m "feat(antifraud): emotion-immunity prompt rule for business/lending topics"
```

---

## Task 4: 纯函数 `business-ledger.js` — 业务升级状态机

**Files:**
- Create: `ui/static/business-ledger.js`
- Test: `ui/static/business-ledger.test.mjs`

- [ ] **Step 1: Write the failing test**

Create `ui/static/business-ledger.test.mjs`:
```js
import { test } from "node:test";
import assert from "node:assert/strict";
import mod from "./business-ledger.js";
const { createBusinessIntegrity } = mod;

test("连续3条业务矛盾 → flagged，只产出一次 flagged finding", () => {
  const s = createBusinessIntegrity();
  const out1 = s.applyContradictions([{ field: "业务不一致·借款金额", stated: "本次：1000万", known: "此前：500万", kind: "business_integrity" }]);
  assert.equal(s.state, "challenged");
  assert.equal(out1.flaggedFinding, null);
  s.applyContradictions([{ field: "业务不一致·用途·厂房", stated: "本次：800万", known: "此前：300万", kind: "business_integrity" }]);
  assert.equal(s.state, "evidence_required");
  const out3 = s.applyContradictions([{ field: "业务不一致·用途·设备", stated: "本次：200万", known: "此前：100万", kind: "business_integrity" }]);
  assert.equal(s.state, "flagged");
  assert.ok(out3.flaggedFinding);
  assert.equal(out3.flaggedFinding.severity, "high");
  // 第4条不再重复产出 flagged
  const out4 = s.applyContradictions([{ field: "业务不一致·借款金额", stated: "本次：2000万", known: "此前：1000万", kind: "business_integrity" }]);
  assert.equal(out4.flaggedFinding, null);
});

test("clarified 清空 outstanding → 回落 none（未 flagged 前）", () => {
  const s = createBusinessIntegrity();
  s.applyContradictions([{ field: "业务不一致·借款金额", stated: "本次：1000万", known: "此前：500万" }]);
  assert.equal(s.state, "challenged");
  s.applyClarified(["loan_total"]); // 映射到 借款金额 字段
  assert.equal(s.state, "none");
  assert.equal(s.hits, 0);
});

test("flagged 后 clarified 不回落", () => {
  const s = createBusinessIntegrity();
  s.applyContradictions([{ field: "业务不一致·A" }]);
  s.applyContradictions([{ field: "业务不一致·B" }]);
  s.applyContradictions([{ field: "业务不一致·C" }]);
  assert.equal(s.state, "flagged");
  s.applyClarified(["A", "B", "C"]);
  assert.equal(s.state, "flagged");
});

test("空矛盾不推进", () => {
  const s = createBusinessIntegrity();
  const out = s.applyContradictions([]);
  assert.equal(s.state, "none");
  assert.equal(out.flaggedFinding, null);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test ui/static/business-ledger.test.mjs`
Expected: FAIL（`Cannot find module './business-ledger.js'` 或 `createBusinessIntegrity is not a function`）

- [ ] **Step 3: Write minimal implementation**

Create `ui/static/business-ledger.js`（双导出：浏览器挂 window，node 走 module.exports）：
```js
// 业务升级状态机（纯逻辑，无 DOM/无 IO）。
// none → challenged → evidence_required → flagged；clarified 清空 outstanding 则回落（未 flagged 前）。
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;       // node 测试
  if (typeof window !== "undefined") window.BusinessLedger = api;                   // 浏览器
})(this, function () {
  // 从 clarified 的字段名（loan_total / industry / 厂房…）粗映射到 contradiction.field 文案关键字
  function fieldKey(contradictionField) {
    // "业务不一致·借款金额" → "借款金额"
    const i = contradictionField.indexOf("·");
    return i >= 0 ? contradictionField.slice(i + 1) : contradictionField;
  }

  function createBusinessIntegrity() {
    const s = {
      state: "none",
      hits: 0,
      flaggedLogged: false,
      lastHitAt: 0,
      outstanding: [], // 未澄清矛盾的 field 关键字集合

      applyContradictions(contradictions) {
        const list = Array.isArray(contradictions) ? contradictions : [];
        let flaggedFinding = null;
        for (const c of list) {
          if (!c || !c.field) continue;
          const key = fieldKey(c.field);
          if (!this.outstanding.includes(key)) this.outstanding.push(key);
          this.hits += 1;
          this.lastHitAt = Date.now();
          this.state = this.hits >= 3 ? "flagged" : this.hits === 2 ? "evidence_required" : "challenged";
        }
        if (this.state === "flagged" && !this.flaggedLogged && list.length) {
          this.flaggedLogged = true;
          flaggedFinding = {
            field: "业务不一致·高风险",
            stated: "多处业务说法前后变卦",
            known: "经核对与取证仍无法对上",
            severity: "high",
            kind: "business_integrity",
            ts: Date.now() / 1000,
          };
        }
        return { state: this.state, flaggedFinding };
      },

      applyClarified(fields) {
        if (this.flaggedLogged) return; // 已坐实，不回落
        const keys = (Array.isArray(fields) ? fields : []).map(String);
        // clarified 用字段英文名(loan_total/industry/…)；outstanding 用中文关键字。两边都尝试移除。
        this.outstanding = this.outstanding.filter((k) => !keys.includes(k) && !keys.includes(enToCn(k)) && !keys.includes(cnToEn(k)));
        if (this.outstanding.length === 0) { this.state = "none"; this.hits = 0; }
      },

      reset() { this.state = "none"; this.hits = 0; this.flaggedLogged = false; this.lastHitAt = 0; this.outstanding = []; },
    };
    return s;
  }

  // clarified 的英文字段名 ↔ contradiction 文案关键字 的粗映射
  const EN_CN = { loan_total: "借款金额", industry: "经营行业" };
  const CN_EN = Object.fromEntries(Object.entries(EN_CN).map(([k, v]) => [v, k]));
  function enToCn(k) { return EN_CN[k] || k; }
  function cnToEn(k) { return CN_EN[k] || k; }

  return { createBusinessIntegrity };
});
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --test ui/static/business-ledger.test.mjs`
Expected: PASS（4 个 test 全绿）

- [ ] **Step 5: Commit**

```bash
git add ui/static/business-ledger.js ui/static/business-ledger.test.mjs
git commit -m "feat(antifraud): business-integrity escalation state machine (pure, dual-export)"
```

---

## Task 5: chat.html 引入模块 + chat.js 账本/队列/状态字段

**Files:**
- Modify: `ui/static/chat.html`（约 line 547，在 `realtime-voice.js` 之前/之后）
- Modify: `ui/static/chat.js`（`videoCall` 对象定义、`openVideoCall` 重置）

- [ ] **Step 1: chat.html 引入 business-ledger.js**

在 `<script src="/static/realtime-voice.js"></script>` 之前加一行：
```html
  <script src="/static/business-ledger.js"></script>
```

- [ ] **Step 2: chat.js `videoCall` 对象加字段**

在 `videoCall` 对象定义（含 `sceneDeception` 那块）追加：
```js
  // —— 长程业务一致性 ——
  businessLedger: null,           // openVideoCall 时初始化为空账本
  businessClaimEvents: [],        // [{field,value,unit,raw,ts,seq,event_type}]
  businessIntegrity: null,        // createBusinessIntegrity() 实例，openVideoCall 时建
  businessQueue: [],              // [{text, id, resolve, promise}]
  businessBusy: false,
  skipNextVoiceBusiness: false,   // 文字发送时置真，让紧随的去抖回调跳过"语音业务入队"，避免同句双查
```

- [ ] **Step 3: chat.js 加空账本工厂 + openVideoCall 重置**

在 `videoCall` 定义之后加：
```js
function emptyBusinessLedger() {
  return { loan_total: null, allocations: {}, industry: null, partners: [], business_data: {} };
}
```
在 `openVideoCall` 的重置区（`videoCall.sceneDeception = {...}` 附近）追加：
```js
  videoCall.businessLedger = emptyBusinessLedger();
  videoCall.businessClaimEvents = [];
  videoCall.businessIntegrity = window.BusinessLedger.createBusinessIntegrity();
  videoCall.businessQueue = [];
  videoCall.businessBusy = false;
```

- [ ] **Step 4: 语法检查 + Commit**

```bash
node --check ui/static/chat.js
git add ui/static/chat.html ui/static/chat.js
git commit -m "feat(antifraud): wire business ledger/queue/state fields into video call"
```

---

## Task 6: 串行队列入口 `videoEnqueueBusinessCheck` + drain

**Files:**
- Modify: `ui/static/chat.js`（在 `videoRunContradictionCheck` 附近新增）

- [ ] **Step 1: 实现唯一入口 + drain（含去重/失败/超限）**

在 `videoRunContradictionCheck` 函数之后新增：
```js
let __bizUttSeq = 0;
// 唯一可 await 入口：入队一条 utterance 的业务检测，返回 promise（resolve 携带其 contradictions）。
// 按 utteranceId 去重；语音路径 fire-and-forget 调用，文字路径 await。
function videoEnqueueBusinessCheck(text, utteranceId) {
  const id = utteranceId || `u${++__bizUttSeq}`;
  const existing = videoCall.businessQueue.find((q) => q.id === id);
  if (existing) return existing.promise;
  let resolve;
  const promise = new Promise((r) => { resolve = r; });
  const item = { text: String(text || ""), id, resolve, promise };
  videoCall.businessQueue.push(item);
  // 超限：丢最旧未开始项（队首之后的那条最旧；队首可能在途）并以空结果 resolve
  while (videoCall.businessQueue.length > 8) {
    const idx = videoCall.businessBusy ? 1 : 0; // 在途时保护队首
    const dropped = videoCall.businessQueue.splice(idx, 1)[0];
    if (dropped) dropped.resolve({ contradictions: [] });
  }
  videoDrainBusinessQueue();
  return promise;
}

async function videoDrainBusinessQueue() {
  if (videoCall.businessBusy) return;
  const item = videoCall.businessQueue[0];
  if (!item) return;
  videoCall.businessBusy = true;
  let contradictions = [];
  try {
    const res = await fetch(`${RTC_CFG.apiBase}/api/business-claim-check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ledger: videoCall.businessLedger, utterance: item.text,
        recent: videoCall.transcriptLog.slice(-6).map((t) => `${t.role === "ai" ? "经理" : "用户"}：${t.text}`).join("\n"),
        seq: item.id }),
    });
    if (res.ok) {
      const data = await res.json().catch(() => ({}));
      if (data && data.is_business && Array.isArray(data.claim_events) && data.claim_events.length) {
        if (data.updated_ledger) videoCall.businessLedger = data.updated_ledger;
        for (const ev of data.claim_events) videoCall.businessClaimEvents.push({ ...ev, seq: item.id });
        contradictions = Array.isArray(data.contradictions) ? data.contradictions : [];
        videoApplyBusinessResult(contradictions, data.clarified || [], data.emotional_pressure === true);
      }
    }
  } catch (e) {
    // 失败保守：空结果
  } finally {
    item.resolve({ contradictions });
    videoCall.businessQueue.shift();
    videoCall.businessBusy = false;
    if (videoCall.businessQueue.length) videoDrainBusinessQueue();
  }
}
```

- [ ] **Step 2: 语法检查**

Run: `node --check ui/static/chat.js`
Expected: PASS（`videoApplyBusinessResult` 在 Task 7 定义，暂时引用——若 lint 严格可先放一个空桩，Task 7 补全。这里允许前向引用，因都是函数声明、运行时才调用。）

- [ ] **Step 3: Commit**

```bash
git add ui/static/chat.js
git commit -m "feat(antifraud): serial business-check queue with dedup, overflow and failure-safe drain"
```

---

## Task 7: 结果处理（状态机 + 弹窗/nudge）+ 去抖/文字接入 + 落档

**Files:**
- Modify: `ui/static/chat.js`（`videoApplyBusinessResult`、`videoScheduleContradictionCheck`、`videoSendText`、`videoMergeContradictions`、落档处）

- [ ] **Step 1: 实现 `videoApplyBusinessResult`（喂状态机 + 复用现有弹窗/nudge）**

新增：
```js
// 业务检测结果 → 升级状态机 → 现有弹窗/落库/nudge。
function videoApplyBusinessResult(contradictions, clarified, emotionalPressure) {
  const bi = videoCall.businessIntegrity;
  if (!bi) return;
  if (Array.isArray(clarified) && clarified.length) bi.applyClarified(clarified);
  const list = Array.isArray(contradictions) ? contradictions : [];
  // 每条业务矛盾走现有管线：弹窗 + 落库（videoHandleContradiction 内含去重 + sendContext nudge）
  for (const c of list) videoHandleContradiction(c);
  const { flaggedFinding } = bi.applyContradictions(list);
  if (flaggedFinding) {
    videoRenderRiskAlert(flaggedFinding);
    videoCall.contradictionsLog.push(flaggedFinding);
  }
  // 情绪施压下且有业务矛盾：按状态注入更强 nudge（实时语音通道）
  if (videoCall.client && list.length && (emotionalPressure || bi.state !== "challenged")) {
    const msg = bi.state === "flagged"
      ? "（风控提示：用户多次变卦无法自圆其说，已标记高风险，后续更谨慎；口吻仍客气、不指控。）"
      : bi.state === "evidence_required"
      ? "（风控升级：用户仍变卦/回避且在用情绪施压。这是贷款审批，不能松动。共情但坚定地请其提供能对上的材料证明。）"
      : "（风控提示：用户业务说法前后不一致。共情一句，但务必自然指出这处出入，请其确认或提供材料。）";
    videoCall.client.sendContext(msg);
  }
}
```

- [ ] **Step 2: 去抖回调接入（语音路径 fire-and-forget）**

在 `videoScheduleContradictionCheck` 的 setTimeout 回调里，现有 `videoCheckSceneMismatch(utterance)` 之后追加（用 `skipNextVoiceBusiness` 防与文字路径同句双查）：
```js
    if (videoCall.skipNextVoiceBusiness) {
      videoCall.skipNextVoiceBusiness = false; // 本句已由文字路径检测，跳过
    } else {
      videoEnqueueBusinessCheck(utterance, `voice-${Date.now()}`); // 语音：fire-and-forget
    }
```

- [ ] **Step 3: 文字通道接入（`videoSendText` await + 拼进 messages）**

在 `videoSendText` 里，构造 `parts` 处（`if (visual) parts.push(...)` 附近）之前，先 await 业务检测并把升级话术拼进去：
```js
  // 文字通道：sendContext 无效，必须把业务核验话术直接拼进 /api/video-chat。
  // 先置 skip 标志，防紧随的 videoScheduleContradictionCheck 去抖回调对同句再做一次语音业务入队。
  videoCall.skipNextVoiceBusiness = true;
  let bizNudge = "";
  try {
    const r = await videoEnqueueBusinessCheck(text, `text-${Date.now()}`);
    if (r && r.contradictions && r.contradictions.length) {
      const bi = videoCall.businessIntegrity;
      bizNudge = bi && bi.state === "flagged"
        ? "（风控：用户业务说法多次变卦，已属高风险。共情一句但坚持指出出入、要求材料证明，不松动。）"
        : "（风控：用户业务说法前后不一致。共情一句，但必须指出出入并请其提供材料证明，不因情绪松动。）";
    }
  } catch (e) { /* 业务检测失败不阻塞文字回复 */ }
```
然后在 `parts` 拼装处追加：
```js
    if (bizNudge) parts.push(bizNudge);
```
> 去重说明：`videoSendText` 现有仍调用 `videoScheduleContradictionCheck()`（用于档案/场景检测，保留）。业务检测只走这里的 await 版本；上面置的 `videoCall.skipNextVoiceBusiness = true` 会让 Task 7 Step 2 的去抖回调跳过本句的语音业务入队，从而同句只查一次。注意把"置 skip + await 业务检测"放在 `videoSendText` 调 `videoScheduleContradictionCheck()` 之前。

- [ ] **Step 4: `videoMergeContradictions` 的 high reason 按 kind 分类**

把现有写死的画面欺骗 reason 改为按 contradiction 的 `kind`/`field` 生成：
```js
function videoMergeContradictions(risk, contradictions) {
  const flagged = Array.isArray(contradictions) ? contradictions : [];
  if (!flagged.length) return risk;
  if (!risk) risk = { level: "medium", reasons: [], signals: {} };
  risk.contradictions = flagged;
  const highs = flagged.filter((c) => c && c.severity === "high");
  if (highs.length && risk.level !== "high") {
    risk.level = "high";
    if (!Array.isArray(risk.reasons)) risk.reasons = [];
    const reasons = new Set();
    for (const c of highs) {
      if (c.kind === "business_integrity") reasons.add("通话中检测到业务说法前后不一致（金额/用途/行业等多次变卦，经核对与取证仍无法对上）");
      else reasons.add("通话中检测到疑似画面欺骗（场景与口述多次不符，提示与取证后仍无法对上）");
    }
    for (const r of reasons) risk.reasons.push(r);
  }
  return risk;
}
```

- [ ] **Step 5: 落档加业务审计快照**

在挂断落库处（`videoFinalizeCall` 内构造 `risk` 之后、postJson 之前）追加把账本快照与事件流写进 risk：
```js
  if (risk && typeof risk === "object") {
    risk.business_ledger = videoCall.businessLedger;
    risk.business_claim_events = videoCall.businessClaimEvents;
  }
```
> 因 `videoFinalizeCall` 用快照入参，确保 `businessLedger`/`businessClaimEvents` 在调用时仍是本通的值（reset 发生在其后，安全）。如担心异步竞态，可像 transcript 那样把这两项也作为入参快照传入。

- [ ] **Step 6: 语法检查 + 全量单测**

```bash
node --check ui/static/chat.js
node --test realtime/business-claims.test.mjs ui/static/business-ledger.test.mjs
```
Expected: 语法 OK；两组单测全绿。

- [ ] **Step 7: Commit**

```bash
git add ui/static/chat.js
git commit -m "feat(antifraud): business result handling, voice/text injection, kind-based reason, audit snapshot"
```

---

## Task 8: 端到端人工验证

**Files:** 无（运行验证）

- [ ] **Step 1: 重启服务（venv python + node 代理）**

```bash
export HERMES_HOME="$PWD/.hermes-customer-manager"
lsof -nP -iTCP:8870 -sTCP:LISTEN -t | xargs -r kill; lsof -nP -iTCP:8787 -sTCP:LISTEN -t | xargs -r kill; sleep 1
node realtime/doubao-realtime-proxy.mjs > /tmp/rtc.log 2>&1 &
.venv/bin/python ui/server.py > /tmp/ui.log 2>&1 &
sleep 3; curl -s -o /dev/null -w "ui %{http_code}\n" http://127.0.0.1:8787/healthz
```

- [ ] **Step 2: 浏览器强制刷新并跑用例**

⌘+Shift+R → 视频通话：
1. 说"想借500万，300万厂房、100万设备、100万工资"。
2. 闲聊 10+ 轮（验证业务无关时 AI 顺着、不误报）。
3. 装生气说"早说了要1000万！800万厂房、200万设备！"。

- [ ] **Step 3: 校验现象**

- 第 3 步触发"业务不一致"折叠提示（借款金额 / 用途·厂房 / 用途·设备 三处），工资不报矛盾。
- AI 共情一句但坚持指出出入、要材料，不因生气松动。
- 连续变卦达到 flagged 后，挂断查库：

```bash
.venv/bin/python - <<'PY'
import sqlite3, json
db=sqlite3.connect("ui/data/wewallet.sqlite"); db.row_factory=sqlite3.Row
r=db.execute("SELECT risk FROM video_calls ORDER BY created_ts DESC LIMIT 1").fetchone()
risk=json.loads(r["risk"]) if r["risk"] else {}
print("level:", risk.get("level"))
print("reasons:", risk.get("reasons"))
print("business_claim_events 数:", len(risk.get("business_claim_events", [])))
print("ledger:", json.dumps(risk.get("business_ledger"), ensure_ascii=False))
PY
```
Expected: `level=high`、reasons 含"业务说法前后不一致"、`business_claim_events` 含多条 `event_type:"update"`、`business_ledger` 为最终值。

- [ ] **Step 4: 文字通道验证**

通话里改用打字发"其实要借2000万"，确认 AI 文字回复也指出与此前不一致、要材料（验证文字通道 await 注入生效）。

- [ ] **Step 5: 回归**

确认场景欺骗、档案矛盾、长句不被打断等既有能力不受影响（随便跑一通常规对话）。

---

## 完成标准

- `node --test realtime/business-claims.test.mjs ui/static/business-ledger.test.mjs` 全绿。
- 端到端用例：隔多轮的 500→1000 变卦被抓、情绪下不松动、flagged 落档 high + 审计快照完整。
- 既有能力无回归。
