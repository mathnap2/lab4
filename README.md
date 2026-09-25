# Lab 4 — ALB + Lambda + ElastiCache + RDS (caching performance demo)

Infrastructure-as-code lab that deploys an internet-facing Application Load
Balancer routing directly to a Lambda function, which reads/writes a
PostgreSQL RDS instance and caches results in an ElastiCache Redis cluster.
A load-test tool then proves the performance difference between a cold
(non-cached) request and a warm (cached) request.

Student: Mathias Napoles — 745671

## Architecture

```
                                 Internet
                                    |
                                    v
                         +---------------------+
                         |   ALB (public subnets)|
                         +---------------------+
                                    | invokes (Lambda target group)
                                    v
                         +---------------------+
                         |  Lambda (private subnets) |
                         +---------------------+
                            |                |
                            v                v
                 +------------------+  +------------------+
                 | ElastiCache Redis|  | RDS PostgreSQL   |
                 | (private subnet) |  | (private subnet) |
                 +------------------+  +------------------+
```

- **VPC**: dedicated VPC (`10.0.0.0/16`) with 2 public subnets (ALB) and 2
  private subnets (Lambda, RDS, ElastiCache) across 2 AZs. Private subnets
  have no route to the internet — the Lambda code never needs it, it only
  talks to RDS/ElastiCache inside the VPC.
- **ALB**: internet-facing, HTTP:80, forwards to a `target_type = "lambda"`
  target group (no EC2/containers involved).
- **Lambda**: Python 3.12, VPC-attached, uses the AWS Academy `LabRole`
  (Academy does not allow creating custom IAM roles).
- **RDS**: PostgreSQL `db.t3.micro`, private, seeds a 5,000-row `items` table
  on first cold start.
- **ElastiCache**: Redis `cache.t3.micro`, single node, private.

### API

| Path                | Method | Description                                         |
|---------------------|--------|------------------------------------------------------|
| `/health`           | GET    | Used by the ALB target group health check.           |
| `/wo_cache/{id}`     | GET    | Returns item `id`, **always** querying RDS directly (artificial 150ms delay + aggregation query). Cache is never read or written. `X-Cache: DISABLED`. |
| `/w_cache/{id}`      | GET    | Returns item `id` through the Redis cache-aside pattern. First call per id -> `X-Cache: MISS` (queries RDS, stores in Redis for 120s). Subsequent calls -> `X-Cache: HIT` (served from Redis, no RDS round trip). |
| `/flush`            | POST   | Flushes the Redis cache (used by the load test tool to force a clean "cold" run). |

Both item routes return a `server_elapsed_ms` field in the JSON body and an
`X-Cache` response header (`DISABLED`, `MISS` or `HIT`), so the difference is
visible with a plain `curl -D -`.

## Prerequisites

- Terraform >= 1.5
- Python 3.9+ (only used to run the load test script; no third-party
  packages required — it's stdlib only)
- An active **AWS Academy Learner Lab** session, with credentials exported
  under an AWS CLI profile named `academy`:

  ```bash
  aws configure --profile academy
  # paste Access Key ID / Secret Access Key / Session Token from the
  # Academy Lab "AWS Details" panel, region: us-east-1
  ```

  Verify it works:

  ```bash
  aws sts get-caller-identity --profile academy
  ```

  Learner Lab credentials expire (~4h). If Terraform starts failing with
  auth errors mid-lab, re-export fresh credentials from the Academy panel
  into the `academy` profile and re-run.

## Deploy

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

`terraform apply` will:
1. Create the VPC, subnets, route tables and security groups.
2. Create the RDS PostgreSQL instance and ElastiCache Redis cluster (RDS
   alone typically takes 5-8 minutes to become available).
3. `pip install` the Lambda's dependencies as Linux wheels and zip the
   function automatically (no manual packaging step).
4. Create the Lambda function, the ALB, its listener and Lambda target group.

When it finishes, note the outputs:

```bash
terraform output
```

Take a screenshot of this successful `terraform apply` output (and of
`terraform output`) for the report.

## Verify it's working

```bash
curl -D - http://<alb_dns_name>/health

curl -D - http://<alb_dns_name>/wo_cache/42   # always X-Cache: DISABLED, ~300ms
curl -D - http://<alb_dns_name>/wo_cache/42   # still ~300ms, cache is never used

curl -D - http://<alb_dns_name>/w_cache/42    # first call: X-Cache: MISS, ~300ms
curl -D - http://<alb_dns_name>/w_cache/42    # second call: X-Cache: HIT, ~1-2ms
```

Then check the AWS Console and take screenshots of:
- VPC (subnets, route tables)
- EC2 > Load Balancers (the ALB, its listener, its target group showing the
  Lambda target as **healthy**)
- Lambda function (configuration, VPC config, environment variables — the
  DB password will be hidden by Terraform, but double check the console
  doesn't expose it either)
- RDS instance (status "Available")
- ElastiCache Redis cluster (status "Available")
- CloudWatch Logs for the Lambda function, showing invocations

## Run the load test (cache-miss vs cache-hit performance)

```bash
cd ../loadtest
python loadtest.py --url http://<alb_dns_name> --requests 200 --concurrency 25
```

This runs 3 phases against the same pool of item ids, at the given concurrency:
1. **Phase 1 - `/wo_cache`**: 200 requests, cache bypassed on every single one
   (baseline: always pays the RDS round trip + the artificial 150ms delay).
2. **Phase 2 - `/w_cache` (cold)**: flushes Redis, then 200 requests -> almost
   all are cache **MISSES** (same cost as phase 1, and populates the cache).
3. **Phase 3 - `/w_cache` (warm)**: re-sends the exact same 200 requests ->
   almost all are cache **HITS** (served from Redis, no RDS round trip).

Prints latency stats (min/avg/max/p95) and the `X-Cache` breakdown for each
phase, plus a final summary with the measured speedup (typically 2-15x faster
on `db.t3.micro` / `cache.t3.micro`, depending on concurrency).

## Stress test with wrk

[wrk](https://github.com/giltene/wrk) is a Linux HTTP benchmarking tool (it
needs epoll, so it doesn't run natively on Windows). Use WSL:

```bash
# one-time setup inside WSL (Ubuntu):
sudo apt-get update && sudo apt-get install -y wrk

# from WSL, at the repo root:
cd loadtest/wrk
./run_wrk_demo.sh http://<alb_dns_name> 15s 4 50
```

Arguments: `<base_url> [duration=15s] [threads=4] [connections=50]`.

This runs the same 3 phases as `loadtest.py` (no cache / cache cold / cache
warm), but driven by wrk's multi-threaded event-loop engine, which sustains
much higher concurrency than the Python script and reports proper
`Requests/sec` and latency percentiles (p50/p90/p99) per phase — the numbers
to screenshot for the "stress" part of the report. `wrk_script.lua` cycles
requests through a fixed pool of 200 item ids (seeded deterministically, so
the same ids are reused across phase 2 and phase 3) and tallies the
`X-Cache` header breakdown, printed at the end of each run.

Take a screenshot of this terminal output for the report — this is the core
evidence of the caching performance improvement.

Optional: to see the Lambda's own concurrency behave under stress, set
`lambda_reserved_concurrency` in `terraform.tfvars` to a small number (e.g.
`5`), re-apply, and re-run the load test with higher `--concurrency` to
observe throttled/slower responses.

## Cleanup (important — do this before your Academy Lab session ends)

```bash
cd terraform
terraform destroy
```

Leaving RDS/ElastiCache running burns your Learner Lab budget and they will
be force-terminated anyway when the lab session ends, which can leave
orphaned resources in Terraform's state. Always destroy when you're done.

## Repository layout

```
lab4/
├── terraform/        # All infrastructure (VPC, ALB, Lambda, RDS, ElastiCache)
├── lambda/            # Lambda handler source (app.py) + requirements.txt
├── loadtest/          # Load-test tool (loadtest.py, stdlib only)
├── docs/screenshots/  # Put your evidence screenshots here
└── README.md
```

## Deliverable checklist

- [ ] GitHub repo pushed with all this code
- [ ] `Lab4_745671.pdf` containing:
  - [ ] Student email visible
  - [ ] GitHub repo URL
  - [ ] Screenshots of the AWS services deployed (VPC, ALB, Lambda, RDS, ElastiCache)
  - [ ] Screenshot of `terraform apply` succeeding
  - [ ] Screenshot of the load test terminal output (cold vs warm cache comparison)
