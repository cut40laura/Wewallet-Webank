#!/usr/bin/env python3
"""
为模拟器播种测试账号 —— 把 personas/*.md 里的客户账号幂等写入本地 SQLite。

绕过短信验证码，直接调用项目的 auth.create_user()。已存在的账号会跳过。
账号与本地 server.py 共用同一个数据库（config.DATA_DIR / wewallet.sqlite）。

用法（在项目根或 simulator/ 下均可）：
    python3.13 simulator/seed_personas.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "ui"))

import auth  # noqa: E402  (依赖 ui/ 在 sys.path 上)
from user_simulator import PERSONAS  # noqa: E402


def main() -> None:
    created, skipped, failed = 0, 0, 0
    for key, p in PERSONAS.items():
        phone = auth.normalize_phone(p["phone"])
        password = p["password"]
        if not phone or not password:
            print(f"  ⚠️  {key}: 缺少 phone/password，跳过")
            failed += 1
            continue
        if auth.find_user_by_phone(phone):
            print(f"  ⏭️  {p['name']} ({phone}) 已存在，跳过")
            skipped += 1
            continue
        try:
            auth.create_user(phone, password)
            print(f"  ✅ 创建 {p['name']} ({phone})")
            created += 1
        except Exception as e:  # noqa: BLE001
            print(f"  ❌ {p['name']} ({phone}) 创建失败: {e}")
            failed += 1

    print(f"\n播种完成：新建 {created} | 已存在 {skipped} | 失败 {failed}")


if __name__ == "__main__":
    main()
