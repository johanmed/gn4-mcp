#!/bin/sh
# Start/stop/status for the GN4 MCP server, following this box's existing
# pattern for genenetwork4 itself (nohup + pid file; no supervisor here).
#
#   ./start.sh          start; verifies the server actually came up
#   ./start.sh stop     stop; waits until the port is released
#   ./start.sh status   report
#   ./start.sh restart  stop, then start

cd "$(dirname "$0")" || exit 1

PIDFILE=/tmp/gn4-mcp.pid
LOG=/tmp/gn4-mcp.log
HOST=127.0.0.1
PORT=9000
# Full protocol path; must match the nginx location that forwards to us.
MCP_PATH=/gn4-mcp/mcp
API=https://vesuvio.pu.ac.ke/gn4
STARTUP_TIMEOUT=30   # seconds to wait for the server to answer

server_pid() {
    # Print the pid from $PIDFILE only if that process is really our server
    # (guards against a stale pidfile whose pid was reused by another proc).
    [ -f "$PIDFILE" ] || return 1
    pid=$(cat "$PIDFILE" 2>/dev/null) || return 1
    [ -n "$pid" ] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    case "$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)" in
      *server.py*) echo "$pid"; return 0 ;;
      *) return 1 ;;
    esac
}

is_up() {
    # The MCP endpoint answers an initialize probe.
    curl -s -m 3 -o /dev/null -X POST "http://$HOST:$PORT$MCP_PATH" \
      -H 'Content-Type: application/json' -H 'Accept: application/json' \
      -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"start-sh","version":"0"}}}'
}

do_stop() {
    pid=$(server_pid) || { echo "not running"; rm -f "$PIDFILE"; return 0; }
    kill "$pid" 2>/dev/null
    # Wait for the process to exit and the port to be released (uvicorn
    # shuts down gracefully; give it time, then insist).
    i=0
    while kill -0 "$pid" 2>/dev/null && [ "$i" -lt 100 ]; do
        i=$((i + 1)); sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
        echo "forcing kill $pid"; kill -9 "$pid" 2>/dev/null
        sleep 1
    fi
    rm -f "$PIDFILE"
    echo "stopped (was pid $pid)"
}

do_start() {
    if pid=$(server_pid); then
        echo "already running (pid $pid)"; exit 0
    fi
    rm -f "$PIDFILE"

    nohup ./.venv/bin/python server.py \
      "$API" --target-port "$PORT" --host "$HOST" --path "$MCP_PATH" \
      >> "$LOG" 2>&1 &
    echo $! > "$PIDFILE"

    # Verify it actually started: spec fetch + bind happen after the
    # shell regains control, so poll until the endpoint answers.
    i=0
    while [ "$i" -lt $((STARTUP_TIMEOUT * 10)) ]; do
        if is_up; then
            echo "started (pid $(cat "$PIDFILE"))"
            echo "  endpoint: http://$HOST:$PORT$MCP_PATH"
            echo "  log:      $LOG"
            exit 0
        fi
        # Died while starting up?  Report and show why.
        if ! kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
            echo "FAILED to start; last log lines:" >&2
            tail -n 15 "$LOG" >&2
            rm -f "$PIDFILE"
            exit 1
        fi
        i=$((i + 1)); sleep 0.1
    done
    echo "started but not answering within ${STARTUP_TIMEOUT}s; last log lines:" >&2
    tail -n 15 "$LOG" >&2
    exit 1
}

case "$1" in
  stop)    do_stop ;;
  status)
    if pid=$(server_pid); then
        echo "running (pid $pid)"
    else
        echo "not running"
    fi ;;
  restart) do_stop; do_start ;;
  start)   do_start ;;
  "")      do_start ;;
  *) echo "usage: $0 [start|stop|restart|status]"; exit 2 ;;
esac
