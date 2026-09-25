#!/usr/bin/env python3
"""
Load-test tool for the ALB + Lambda + ElastiCache + RDS lab.

The API exposes two explicit routes so the caching effect can be toggled on
purpose instead of relying on TTLs:

  /wo_cache/{id}  -> always queries RDS directly (cache is never touched).
  /w_cache/{id}   -> cache-aside through Redis (MISS the first time per id,
                     HIT afterwards, until the TTL expires).

This script runs three phases against the same pool of item ids:

  Phase 1 "SIN CACHE"        : N requests to /wo_cache/{id}. Every request
                                pays the full RDS round trip.
  Phase 2 "CON CACHE (fria)" : flushes Redis, then N requests to
                                /w_cache/{id}. Almost every request is a
                                cache MISS (same cost as phase 1).
  Phase 3 "CON CACHE (caliente)": the exact same N requests to /w_cache/{id}
                                again. Almost every request is now a cache
                                HIT, served straight from Redis.

Usage:
    python loadtest.py --url http://<alb-dns-name> --requests 200 --concurrency 25
"""

import argparse
import concurrent.futures
import random
import statistics
import time
import urllib.error
import urllib.request


def call(url, method="GET"):
    start = time.perf_counter()
    try:
        req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=20) as resp:
            resp.read()
            elapsed_ms = (time.perf_counter() - start) * 1000
            return {
                "ok": True,
                "status": resp.status,
                "cache": resp.headers.get("X-Cache", "UNKNOWN"),
                "elapsed_ms": elapsed_ms,
            }
    except urllib.error.HTTPError as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {"ok": False, "status": e.code, "error": str(e), "elapsed_ms": elapsed_ms}
    except Exception as e:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - start) * 1000
        return {"ok": False, "status": None, "error": str(e), "elapsed_ms": elapsed_ms}


def run_batch(base_url, endpoint, ids, concurrency):
    urls = [f"{base_url}/{endpoint}/{i}" for i in ids]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        for result in ex.map(call, urls):
            results.append(result)
    return results


def summarize(results, label):
    oks = [r for r in results if r["ok"]]
    failed = len(results) - len(oks)
    latencies = sorted(r["elapsed_ms"] for r in oks)
    cache_counts = {}
    for r in oks:
        c = r.get("cache", "UNKNOWN")
        cache_counts[c] = cache_counts.get(c, 0) + 1

    print(f"\n== {label} ==")
    print(f"requests: {len(results)}   ok: {len(oks)}   failed: {failed}")
    print(f"X-Cache breakdown: {cache_counts}")

    if latencies:
        p95_idx = max(0, int(len(latencies) * 0.95) - 1)
        avg = statistics.mean(latencies)
        print(
            f"latency ms -> min: {latencies[0]:.1f}  "
            f"avg: {avg:.1f}  "
            f"max: {latencies[-1]:.1f}  "
            f"p95: {latencies[p95_idx]:.1f}"
        )
        return avg
    return None


def flush_cache(base_url):
    print("Flushing Redis cache on target ...")
    result = call(f"{base_url}/flush", method="POST")
    if not result["ok"]:
        print(f"  warning: flush request failed: {result.get('error')}")
    else:
        print("  cache flushed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", required=True, help="Base URL of the ALB, e.g. http://my-alb-123.us-east-1.elb.amazonaws.com")
    parser.add_argument("--requests", type=int, default=200, help="Number of requests per phase (default: 200)")
    parser.add_argument("--concurrency", type=int, default=25, help="Concurrent workers (default: 25)")
    parser.add_argument("--item-range", type=int, default=5000, help="Item ids are randomly picked from [1, item-range] (default: 5000, matches seeded rows)")
    parser.add_argument("--pool-size", type=int, default=None, help="Distinct item ids to reuse across requests; default = --requests (all unique ids)")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    pool_size = args.pool_size or args.requests
    pool_size = max(1, min(pool_size, args.requests))

    pool = [random.randint(1, args.item_range) for _ in range(pool_size)]
    ids = [pool[i % pool_size] for i in range(args.requests)]

    print(f"Target: {base_url}")
    print(f"Requests per phase: {args.requests}   Concurrency: {args.concurrency}   Distinct ids: {pool_size}")

    print(f"\nPhase 1: {args.requests} requests to /wo_cache (cache bypassed on every request) ...")
    results_nocache = run_batch(base_url, "wo_cache", ids, args.concurrency)
    avg_nocache = summarize(results_nocache, "Phase 1: SIN CACHE (/wo_cache)")

    flush_cache(base_url)

    print(f"\nPhase 2: {args.requests} requests to /w_cache, cache just flushed (expect mostly MISS) ...")
    results_cold = run_batch(base_url, "w_cache", ids, args.concurrency)
    avg_cold = summarize(results_cold, "Phase 2: CON CACHE - fria (/w_cache, post-flush)")

    print(f"\nPhase 3: same {args.requests} requests to /w_cache again (expect mostly HIT) ...")
    results_warm = run_batch(base_url, "w_cache", ids, args.concurrency)
    avg_warm = summarize(results_warm, "Phase 3: CON CACHE - caliente (/w_cache, warmed up)")

    print("\n=== SUMMARY ===")
    if avg_nocache is not None:
        print(f"Avg latency /wo_cache (siempre sin cache):     {avg_nocache:.1f} ms")
    if avg_cold is not None:
        print(f"Avg latency /w_cache  (cache fria, post-flush): {avg_cold:.1f} ms")
    if avg_warm is not None:
        print(f"Avg latency /w_cache  (cache caliente):         {avg_warm:.1f} ms")
    if avg_nocache and avg_warm:
        print(f"\nSpeedup con cache caliente vs sin cache: {avg_nocache / avg_warm:.2f}x mas rapido")
    if avg_cold and avg_warm:
        print(f"Speedup cache caliente vs cache fria:    {avg_cold / avg_warm:.2f}x mas rapido")


if __name__ == "__main__":
    main()
