#!/usr/bin/env bash
# Source only inside the CI-owned nested session; never select a PID by name.
stop_owned_process() {
  local process_id="${1:-}"
  [[ "$process_id" =~ ^[0-9]+$ ]] || return 0
  printf 'TEARDOWN pid=%s TERM\n' "$process_id"
  kill -TERM "$process_id" 2>/dev/null || true
  for _ in {1..20}; do
    if ! kill -0 "$process_id" 2>/dev/null; then break; fi
    sleep 0.25
  done
  if kill -0 "$process_id" 2>/dev/null; then
    printf 'TEARDOWN pid=%s KILL after 5s\n' "$process_id"
    kill -KILL "$process_id" 2>/dev/null || true
  fi
  wait "$process_id" 2>/dev/null || true
  printf 'TEARDOWN pid=%s reaped\n' "$process_id"
}
