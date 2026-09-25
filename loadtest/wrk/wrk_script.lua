-- wrk load script for the ALB + Lambda + ElastiCache + RDS lab.
--
-- Picks a random item id from a fixed-size pool on every request and hits
-- either /wo_cache/{id} or /w_cache/{id} (selected via the WRK_PATH env var).
-- The pool is generated with a fixed random seed so the SAME set of ids is
-- used across separate wrk invocations -- this is what lets a "cold" run
-- against /w_cache populate the cache and a following "warm" run reuse it.
--
-- Env vars (all optional):
--   WRK_PATH        "w_cache" (default) or "wo_cache"
--   WRK_ITEM_RANGE   upper bound for item ids, default 5000 (matches seeded rows)
--   WRK_POOL_SIZE    how many distinct ids to cycle through, default 200
--
-- wrk's own --latency output already reports requests/sec and latency
-- percentiles (p50/p90/p99) per run, which is the evidence used in the
-- report; use curl or loadtest.py to inspect the X-Cache header per request
-- (per-thread Lua state in wrk isn't reliably readable from done()).

math.randomseed(42)

local base_path = os.getenv("WRK_PATH") or "w_cache"
local item_range = tonumber(os.getenv("WRK_ITEM_RANGE") or "5000")
local pool_size = tonumber(os.getenv("WRK_POOL_SIZE") or "200")

local pool = {}
for i = 1, pool_size do
    pool[i] = math.random(1, item_range)
end

request = function()
    local id = pool[math.random(1, pool_size)]
    local path = "/" .. base_path .. "/" .. id
    return wrk.format("GET", path)
end
