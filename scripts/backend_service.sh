#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${CYBER_BACKEND_ENV_FILE:-"$PROJECT_ROOT/.env.local"}"

load_env() {
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  fi
}

load_env

PYTHON_BIN="${CYBER_BACKEND_PYTHON:-"$PROJECT_ROOT/.venv/bin/python"}"
GUNICORN_BIN="${CYBER_GUNICORN_BIN:-"$PROJECT_ROOT/.venv/bin/gunicorn"}"
BACKEND_RUNNER="${CYBER_BACKEND_RUNNER:-auto}"
GUNICORN_WORKERS="${CYBER_GUNICORN_WORKERS:-2}"
GUNICORN_THREADS="${CYBER_GUNICORN_THREADS:-4}"
GUNICORN_TIMEOUT="${CYBER_GUNICORN_TIMEOUT:-120}"
HOST="${CYBER_BACKEND_HOST:-0.0.0.0}"
PORT="${CYBER_BACKEND_PORT:-5004}"
LOG_FILE="${CYBER_BACKEND_LOG_FILE:-"$PROJECT_ROOT/backend_server.log"}"
PID_FILE="${CYBER_BACKEND_PID_FILE:-"$PROJECT_ROOT/backend_server.pid"}"

pid_from_file() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(tr -cd '0-9' < "$PID_FILE")"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      printf '%s\n' "$pid"
      return 0
    fi
  fi
  return 1
}

pid_from_port() {
  ss -ltnp 2>/dev/null \
    | sed -n "s/.*:${PORT}[[:space:]].*pid=\([0-9]*\).*/\1/p" \
    | head -n 1
}

status() {
  local pid
  pid="$(pid_from_file || true)"
  if [[ -z "$pid" ]]; then
    pid="$(pid_from_port || true)"
  fi
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "running pid=$pid port=$PORT"
    return 0
  fi
  echo "stopped port=$PORT"
  return 3
}

start() {
  local existing_pid
  existing_pid="$(pid_from_port || true)"
  if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
    echo "backend already running pid=$existing_pid port=$PORT"
    echo "$existing_pid" > "$PID_FILE"
    return 0
  fi

  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "python not found or not executable: $PYTHON_BIN" >&2
    return 1
  fi

  cd "$PROJECT_ROOT"
  local runner="$BACKEND_RUNNER"
  if [[ "$runner" == "auto" ]]; then
    if [[ -x "$GUNICORN_BIN" ]]; then
      runner="gunicorn"
    else
      runner="flask"
    fi
  fi

  if [[ "$runner" == "gunicorn" ]]; then
    if [[ ! -x "$GUNICORN_BIN" ]]; then
      echo "gunicorn not found or not executable: $GUNICORN_BIN" >&2
      return 1
    fi
    setsid "$GUNICORN_BIN" \
      --bind "$HOST:$PORT" \
      --workers "$GUNICORN_WORKERS" \
      --threads "$GUNICORN_THREADS" \
      --timeout "$GUNICORN_TIMEOUT" \
      --access-logfile - \
      --error-logfile - \
      "backend.run:app" \
      > "$LOG_FILE" 2>&1 < /dev/null &
  elif [[ "$runner" == "flask" ]]; then
    setsid "$PYTHON_BIN" -c "from backend.app import create_app; app = create_app(); app.run(debug=False, use_reloader=False, host='$HOST', port=$PORT)" \
      > "$LOG_FILE" 2>&1 < /dev/null &
  else
    echo "unsupported backend runner: $runner" >&2
    return 2
  fi
  local pid=$!
  echo "$pid" > "$PID_FILE"
  sleep 1

  if ! kill -0 "$pid" 2>/dev/null; then
    echo "backend failed to start; see $LOG_FILE" >&2
    rm -f "$PID_FILE"
    return 1
  fi
  echo "started pid=$pid port=$PORT runner=$runner log=$LOG_FILE"
}

stop() {
  local pid
  pid="$(pid_from_file || true)"
  if [[ -z "$pid" ]]; then
    pid="$(pid_from_port || true)"
  fi
  if [[ -z "$pid" ]]; then
    rm -f "$PID_FILE"
    echo "backend already stopped"
    return 0
  fi

  kill "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$PID_FILE"
      echo "stopped pid=$pid"
      return 0
    fi
    sleep 0.2
  done

  echo "backend did not stop after TERM; sending KILL pid=$pid" >&2
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$PID_FILE"
}

case "${1:-status}" in
  start)
    start
    ;;
  stop)
    stop
    ;;
  restart)
    stop
    start
    ;;
  status)
    status
    ;;
  *)
    echo "usage: $0 {start|stop|restart|status}" >&2
    exit 2
    ;;
esac
