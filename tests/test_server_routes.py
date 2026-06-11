"""Route-table sanity checks for the web server.

Every route must point at a real Handler method, and security-sensitive
endpoints must declare the right auth level — this is the regression net
for "added an endpoint, forgot the auth check".

Run from the project root (use the anaconda python, see README):
    python3 -m unittest tests.test_server_routes -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("WEWALLET_AUTH_SECRET", "test-secret")
os.environ.setdefault("WEWALLET_DB", str(Path(tempfile.mkdtemp(prefix="wewallet-test-routes-")) / "test.sqlite"))

sys.path.insert(0, str(REPO_ROOT / "ui"))

import server  # noqa: E402

VALID_AUTH_LEVELS = {"public", "user", "enterprise"}

# 唯一允许 public 的端点白名单：新增 public 路由必须有意识地加进来。
ALLOWED_PUBLIC = {
    "/healthz",
    "/api/auth/me",
    "/api/auth/sms/send",
    "/api/auth/sms/verify",
    "/api/auth/password/login",
    "/api/auth/register",
    "/api/auth/logout",
    "/api/voicecall/realtime-config",  # 自行校验登录态，未登录只返回 placeholder 配置
}


class RouteTableTestCase(unittest.TestCase):
    def _check_table(self, routes: dict) -> None:
        for path, (handler_name, auth_level) in routes.items():
            with self.subTest(path=path):
                self.assertTrue(path.startswith("/"), f"{path} 不是合法路径")
                self.assertIn(auth_level, VALID_AUTH_LEVELS)
                handler = getattr(server.Handler, handler_name, None)
                self.assertIsNotNone(handler, f"{path} 指向不存在的方法 {handler_name}")
                self.assertTrue(callable(handler))

    def test_get_routes_wired(self) -> None:
        self._check_table(server.Handler.GET_ROUTES)

    def test_post_routes_wired(self) -> None:
        self._check_table(server.Handler.POST_ROUTES)

    def test_public_endpoints_are_allowlisted(self) -> None:
        for routes in (server.Handler.GET_ROUTES, server.Handler.POST_ROUTES):
            for path, (_name, auth_level) in routes.items():
                if auth_level == "public":
                    self.assertIn(
                        path,
                        ALLOWED_PUBLIC,
                        f"{path} 声明为 public 但不在白名单里——确认无需登录后再加入 ALLOWED_PUBLIC",
                    )

    def test_sensitive_endpoints_require_auth(self) -> None:
        cases = {
            "/api/knowledge/reindex": server.Handler.POST_ROUTES,
            "/api/chat": server.Handler.POST_ROUTES,
            "/api/chat/stream": server.Handler.POST_ROUTES,
            "/api/voicecall": server.Handler.POST_ROUTES,
            "/api/messages": server.Handler.GET_ROUTES,
            "/api/knowledge/status": server.Handler.GET_ROUTES,
        }
        for path, table in cases.items():
            with self.subTest(path=path):
                self.assertIn(path, table)
                self.assertNotEqual(table[path][1], "public", f"{path} 不应是 public")


if __name__ == "__main__":
    unittest.main()
