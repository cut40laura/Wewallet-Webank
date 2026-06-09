#!/usr/bin/env python3
"""
批量模拟器 — 依次运行所有客户画像，生成对比报告。
用法: python3 batch_run.py
"""

import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from user_simulator import run_simulation, PERSONAS

PERSONA_ORDER = ["laowang", "xiaoqin", "laochen", "alex", "laozhou"]
MAX_TURNS = 10

results = []
start_time = time.time()

print("=" * 70)
print("🚀 批量模拟启动 — 5 位客户依次对话")
print(f"   最大轮数: {MAX_TURNS} | 客户自主决定终止")
print("=" * 70)

for i, key in enumerate(PERSONA_ORDER, 1):
    persona = PERSONAS[key]
    print(f"\n{'#' * 70}")
    print(f"# [{i}/5] {persona['name']} — {persona['enterprise_name']}")
    print(f"# 耐心:{persona.get('patience',0):.0%} 礼貌:{persona.get('politeness',0):.0%} 多疑:{persona.get('suspicion',0):.0%}")
    print(f"{'#' * 70}")

    try:
        result = run_simulation(
            persona_key=key,
            max_turns=MAX_TURNS,
            verbose=True,
        )
        result["persona_key"] = key
        results.append(result)
    except Exception as e:
        print(f"  ❌ 模拟失败: {e}")
        results.append({"persona_key": key, "error": str(e)})

    # 严格隔离：间隔足够长，确保上一个会话完全清理
    if i < len(PERSONA_ORDER):
        gap = 5
        print(f"\n🔒 信息隔离中... {gap}s 后开始下一位客户")
        time.sleep(gap)

elapsed = time.time() - start_time

# ============================================================
# 汇总报告
# ============================================================

print("\n\n")
print("=" * 70)
print("📊 批量模拟汇总报告")
print(f"   耗时: {elapsed:.0f}s | 客户数: {len(results)}")
print("=" * 70)

print(f"\n{'客户':<8} {'行业':<14} {'轮数':<5} {'终止':<6} {'综合':<6} {'理解':<6} {'人情':<6} {'专业':<6} {'风控':<6} {'推进':<6}")
print("-" * 85)

for r in results:
    if "error" in r:
        print(f"{r['persona_key']:<8} {'ERROR':<14} {'-':<5} {'-':<6} {r['error'][:30]}")
        continue
    key = r.get("persona_key", "?")
    persona = PERSONAS.get(key, {})
    name = persona.get("name", key)
    industry_map = {
        "laowang": "餐饮", "xiaoqin": "美容", "laochen": "五金建材",
        "alex": "跨境电商", "laozhou": "模具制造",
    }
    industry = industry_map.get(key, "?")
    s = r.get("avg_scores", {})
    term = "主动终止" if r.get("terminated") else "到上限"
    print(f"{name:<8} {industry:<14} {r['turns']:<5} {term:<6} "
          f"{s.get('overall',0):.0%}   {s.get('relevance',0):.0%}   "
          f"{s.get('empathy',0):.0%}   {s.get('professionalism',0):.0%}   "
          f"{s.get('risk_awareness',0):.0%}   {s.get('progress',0):.0%}")

# 汇总统计
valid = [r for r in results if "error" not in r]
if valid:
    avg_overall = sum(r["avg_scores"]["overall"] for r in valid) / len(valid)
    avg_empathy = sum(r["avg_scores"]["empathy"] for r in valid) / len(valid)
    avg_risk = sum(r["avg_scores"]["risk_awareness"] for r in valid) / len(valid)
    avg_prof = sum(r["avg_scores"]["professionalism"] for r in valid) / len(valid)
    terminated_count = sum(1 for r in valid if r.get("terminated"))
    
    print("-" * 85)
    print(f"{'平均':<8} {'':<14} {'':<5} {'':<6} "
          f"{avg_overall:.0%}   -      "
          f"{avg_empathy:.0%}   {avg_prof:.0%}   "
          f"{avg_risk:.0%}   -")
    print(f"\n🏆 客户主动终止: {terminated_count}/{len(valid)} (客户愿意聊到自然结束)")
    print(f"📈 综合平均分: {avg_overall:.0%}")
    
    # 找出最弱维度
    dims = {"人情味": avg_empathy, "风控意识": avg_risk, "专业度": avg_prof}
    weakest = min(dims, key=dims.get)
    print(f"⚠️  最弱维度: {weakest} ({dims[weakest]:.0%})")

# 保存汇总
report_path = Path(__file__).resolve().parent / "logs" / f"batch_summary_{time.strftime('%Y%m%d_%H%M%S')}.json"
report_path.write_text(json.dumps({
    "timestamp": time.time(),
    "elapsed_seconds": elapsed,
    "max_turns": MAX_TURNS,
    "results": [
        {
            "persona_key": r.get("persona_key", "?"),
            "persona_name": PERSONAS.get(r.get("persona_key", ""), {}).get("name", "?"),
            "turns": r.get("turns", 0),
            "terminated": r.get("terminated", False),
            "termination_reason": r.get("termination_reason", ""),
            "avg_scores": r.get("avg_scores", {}),
            "customer_evaluation": r.get("customer_evaluation", ""),
            "error": r.get("error", ""),
        }
        for r in results
    ],
}, ensure_ascii=False, indent=2), "utf-8")

print(f"\n📁 汇总报告: {report_path}")
print("=" * 70)
