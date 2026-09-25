import json
import os
import time

import psycopg2
import redis

DB_HOST = os.environ["DB_HOST"]
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_NAME = os.environ["DB_NAME"]
DB_USER = os.environ["DB_USER"]
DB_PASSWORD = os.environ["DB_PASSWORD"]

REDIS_HOST = os.environ["REDIS_HOST"]
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

CACHE_TTL_SECONDS = int(os.environ.get("CACHE_TTL_SECONDS", "120"))
SEED_ROWS = int(os.environ.get("SEED_ROWS", "5000"))

# Reused across warm Lambda invocations.
_pg_conn = None
_redis_client = None
_schema_ready = False


def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis_client


def get_pg():
    global _pg_conn
    if _pg_conn is None or _pg_conn.closed:
        _pg_conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            connect_timeout=5,
        )
    return _pg_conn


def ensure_schema(conn):
    global _schema_ready
    if _schema_ready:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                price NUMERIC(10, 2) NOT NULL
            )
            """
        )
        cur.execute("SELECT COUNT(*) FROM items")
        (count,) = cur.fetchone()
        if count == 0:
            cur.execute(
                """
                INSERT INTO items (name, category, price)
                SELECT
                    'Product ' || gs,
                    (ARRAY['electronics','books','clothing','home','sports'])[1 + (gs %% 5)],
                    round((random() * 500 + 5)::numeric, 2)
                FROM generate_series(1, %s) AS gs
                """,
                (SEED_ROWS,),
            )
    conn.commit()
    _schema_ready = True


def response(status, body, extra_headers=None):
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    return {"statusCode": status, "headers": headers, "body": json.dumps(body)}


def query_item(item_id):
    """Always hits RDS. Deliberately simulates a heavier workload (an
    aggregation query + artificial latency) so the cost of skipping the
    cache is clearly visible in the load test results."""
    conn = get_pg()
    ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_sleep(0.15)")
        cur.execute(
            """
            SELECT
                i.id, i.name, i.category, i.price,
                (SELECT COUNT(*) FROM items WHERE category = i.category) AS category_count,
                (SELECT AVG(price) FROM items WHERE category = i.category) AS category_avg_price
            FROM items i
            WHERE i.id = %s
            """,
            (item_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    return {
        "id": row[0],
        "name": row[1],
        "category": row[2],
        "price": float(row[3]),
        "category_count": row[4],
        "category_avg_price": float(row[5]) if row[5] is not None else None,
    }


def handle_wo_cache(item_id):
    """/wo_cache/{id}: always queries RDS directly, cache is never read or
    written. This is the baseline used to stress the server without any
    caching benefit."""
    start = time.perf_counter()
    result = query_item(item_id)
    if result is None:
        return response(404, {"error": "item not found", "id": item_id})

    result["cache"] = "DISABLED"
    result["server_elapsed_ms"] = round((time.perf_counter() - start) * 1000, 2)
    return response(200, result, {"X-Cache": "DISABLED"})


def handle_w_cache(item_id):
    """/w_cache/{id}: cache-aside through Redis. First request for an id is
    a MISS (query RDS + populate Redis); subsequent requests within the TTL
    are HITs served straight from Redis."""
    start = time.perf_counter()
    r = get_redis()
    cache_key = f"item:{item_id}"

    try:
        cached = r.get(cache_key)
    except Exception:
        cached = None

    if cached:
        body = json.loads(cached)
        body["cache"] = "HIT"
        body["server_elapsed_ms"] = round((time.perf_counter() - start) * 1000, 2)
        return response(200, body, {"X-Cache": "HIT"})

    result = query_item(item_id)
    if result is None:
        return response(404, {"error": "item not found", "id": item_id})

    try:
        r.set(cache_key, json.dumps(result), ex=CACHE_TTL_SECONDS)
    except Exception:
        pass

    result["cache"] = "MISS"
    result["server_elapsed_ms"] = round((time.perf_counter() - start) * 1000, 2)
    return response(200, result, {"X-Cache": "MISS"})


def handler(event, context):
    path = event.get("path", "/")
    method = event.get("httpMethod", "GET")

    try:
        if path == "/health":
            return response(200, {"status": "ok"})

        if path == "/flush" and method == "POST":
            get_redis().flushall()
            return response(200, {"flushed": True})

        if path.startswith("/w_cache/"):
            item_id = path.rsplit("/", 1)[-1]
            if not item_id.isdigit():
                return response(400, {"error": "item id must be numeric"})
            return handle_w_cache(int(item_id))

        if path.startswith("/wo_cache/"):
            item_id = path.rsplit("/", 1)[-1]
            if not item_id.isdigit():
                return response(400, {"error": "item id must be numeric"})
            return handle_wo_cache(int(item_id))

        return response(404, {"error": "not found", "path": path})
    except Exception as exc:  # noqa: BLE001 - surface the error to the caller for the demo
        return response(500, {"error": str(exc)})
