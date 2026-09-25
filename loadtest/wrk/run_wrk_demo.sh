#!/usr/bin/env bash
# Stress-tests the deployed ALB with wrk (https://github.com/giltene/wrk)
# across 3 phases: no cache, cache cold, cache warm. Run this from WSL / any
# Linux shell that has wrk installed.
#
# Usage:
#   ./run_wrk_demo.sh http://<alb_dns_name> [duration] [threads] [connections]
#
# Example:
#   ./run_wrk_demo.sh http://lab4-cache-demo-alb-1557498670.us-east-1.elb.amazonaws.com 15s 4 50

set -euo pipefail

BASE_URL="${1:?Usage: run_wrk_demo.sh <base_url> [duration] [threads] [connections]}"
DURATION="${2:-15s}"
THREADS="${3:-4}"
CONNECTIONS="${4:-50}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LUA_SCRIPT="$SCRIPT_DIR/wrk_script.lua"

echo "Target: $BASE_URL"
echo "Duration: $DURATION   Threads: $THREADS   Connections: $CONNECTIONS"

echo
echo "=============================================="
echo "FASE 1: /wo_cache -- SIN CACHE (siempre pega a RDS)"
echo "=============================================="
WRK_PATH=wo_cache wrk -t"$THREADS" -c"$CONNECTIONS" -d"$DURATION" --latency -s "$LUA_SCRIPT" "$BASE_URL"

echo
echo "Flushing Redis cache before the cold run ..."
curl -s -X POST "$BASE_URL/flush" -o /dev/null
echo "done."

echo
echo "=============================================="
echo "FASE 2: /w_cache -- CACHE FRIA (recien flushed, casi todo MISS)"
echo "=============================================="
WRK_PATH=w_cache wrk -t"$THREADS" -c"$CONNECTIONS" -d"$DURATION" --latency -s "$LUA_SCRIPT" "$BASE_URL"

echo
echo "=============================================="
echo "FASE 3: /w_cache -- CACHE CALIENTE (mismo pool de ids, casi todo HIT)"
echo "=============================================="
WRK_PATH=w_cache wrk -t"$THREADS" -c"$CONNECTIONS" -d"$DURATION" --latency -s "$LUA_SCRIPT" "$BASE_URL"

echo
echo "Listo. Compara 'Requests/sec' y 'Latency avg' entre las 3 fases."
