#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HERMES_HOME="$ROOT/.hermes-customer-manager"
cd "$ROOT"

if command -v python3.13 >/dev/null 2>&1; then
  PYTHON_BIN="python3.13"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="python3.11"
else
  PYTHON_BIN="python3"
fi

export HERMES_PYTHON="$PYTHON_BIN"

# 实时通话代理（Node sidecar，端口 8788）：语音/视频通话依赖它。
RTC_PID=""
if command -v node >/dev/null 2>&1; then
  if [ ! -d "$ROOT/realtime/node_modules" ] && command -v npm >/dev/null 2>&1; then
    echo "[realtime] installing ws ..."
    (cd "$ROOT/realtime" && npm install --silent) || echo "[realtime] npm install 失败，语音通话将不可用"
  fi
  node "$ROOT/realtime/doubao-realtime-proxy.mjs" &
  RTC_PID=$!
  trap '[ -n "$RTC_PID" ] && kill "$RTC_PID" 2>/dev/null' EXIT
else
  echo "[realtime] 未检测到 node，语音/视频通话代理未启动（其余功能正常）"
fi

"$PYTHON_BIN" ui/server.py
