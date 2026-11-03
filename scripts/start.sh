#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
PYTHON="$ROOT/.venv/bin/python"

if [ ! -x "$PYTHON" ]; then
    printf '%s\n' '缺少 Python 虚拟环境，请先在项目根目录执行：' \
        '  python3 -m venv .venv' \
        '  .venv/bin/python -m pip install -r backend/requirements-lock.txt' >&2
    exit 1
fi
if ! command -v node >/dev/null 2>&1; then
    printf '%s\n' '未找到 Node.js，请先安装 Node.js 和 npm。' >&2
    exit 1
fi
if [ ! -f "$ROOT/frontend/node_modules/vite/bin/vite.js" ]; then
    printf '%s\n' '缺少前端依赖，请先执行：npm --prefix frontend ci' >&2
    exit 1
fi

# 避免端口冲突时仍启动第二个后台队列处理器；不自动结束已有服务。
"$PYTHON" -I - <<'PY'
import socket
import sys

for port in (8000, 5173):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            print(f"无法使用本地端口 {port}，请检查端口占用；已有服务不会被自动停止。", file=sys.stderr)
            sys.exit(1)
PY

backend_pid=
frontend_pid=
cleanup() {
    trap - EXIT HUP INT TERM
    for pid in "$backend_pid" "$frontend_pid"; do
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid" 2>/dev/null || :
        fi
    done
    for pid in "$backend_pid" "$frontend_pid"; do
        if [ -n "$pid" ]; then
            wait "$pid" 2>/dev/null || :
        fi
    done
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

printf '%s\n' '正在启动 Paper Scout…' \
    '前端：http://127.0.0.1:5173' \
    '后端：http://127.0.0.1:8000' \
    '按 Ctrl+C 同时停止前后端。'

"$PYTHON" -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1 &
backend_pid=$!
(
    cd "$ROOT/frontend"
    # 直接运行 Vite，避免 npm 包装进程退出后遗留开发服务器。
    exec node node_modules/vite/bin/vite.js --config vite.config.ts
) &
frontend_pid=$!

while :; do
    if ! kill -0 "$backend_pid" 2>/dev/null; then
        printf '%s\n' '后端已退出，正在停止前端。' >&2
        wait "$backend_pid"
        exit 1
    fi
    if ! kill -0 "$frontend_pid" 2>/dev/null; then
        printf '%s\n' '前端已退出，正在停止后端。' >&2
        wait "$frontend_pid"
        exit 1
    fi
    sleep 1
done
