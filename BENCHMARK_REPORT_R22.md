# R22 Benchmark Report

## Status

The benchmark harness is complete. A live PostgreSQL 17/TimescaleDB benchmark was **not executed** in the build environment because no disposable `BW_TEST_DATABASE_URL`, PostgreSQL server or container runtime was available.

This is intentionally reported as **not executed**, not as a pass.

## Local executable regression completed

`tests/test_r22_hardening.py` executed the production Top VM SQL builder against 1,503 VM rows and proved the previous 1,000-row candidate bug is removed:

- a low-network VM with the highest guest RAM ranked first under RAM sort
- a low-network VM with the largest disk capacity ranked first under disk sort
- hidden Nodes were excluded before ranking
- Group filtering occurred before ranking
- the SQL path ordered the eligible global set before `LIMIT`

This validates correctness at more than the former 1,000-row cutoff. It is not a substitute for the 60,000-VM PostgreSQL performance run.

## Included tools

### Node, Group and Summary Consumption plans

```bash
./venv/bin/python3 tools/validate-consumption-query-plans.py \
  --dsn "$BW_TEST_DATABASE_URL" \
  --nodes 300 \
  --output /root/r22-consumption-plan.json
```

The tool loads the exact canonical application SQL builder, creates temporary rollup tables, seeds Node data and rejects plans that touch `node_stats`, VM Consumption tables or `vm_uuid`.

### Top VM global sort

```bash
./venv/bin/python3 tools/benchmark-r22-top-vm.py \
  --dsn "$BW_TEST_DATABASE_URL" \
  --synthetic \
  --nodes 300 \
  --vms 60000 \
  --repetitions 5 \
  --output /root/r22-top-vm-benchmark.json
```

Synthetic mode creates PostgreSQL temporary tables only. It does not modify persistent production tables. It benchmarks every existing Top VM sort key with:

```sql
EXPLAIN (ANALYZE, BUFFERS, WAL, FORMAT JSON)
```

The synthetic dataset includes deliberate trap rows:

- `vm-000001`: negligible network, highest RAM
- `vm-000002`: negligible network, largest disk

The benchmark fails if those VMs do not win their corresponding global sorts.

## Required review for a live run

Record and review:

- p50, p95 and maximum execution time for every sort
- rows scanned and rows returned
- shared buffers hit/read
- temporary read/write blocks
- WAL generated
- PostgreSQL CPU and memory
- lock waits, deadlocks and statement timeouts
- five-second refresh under concurrent users
- agent-ingest overlap with Top VM reads

Current Top VM plans must not include raw/history relations. Node, Group and Summary plans must not include raw VM/NIC or VM Consumption relations.

## Release decision

R22 deliberately does not add a snapshot table or extra ingest write path. If the representative 60,000-VM PostgreSQL benchmark fails, retain R21/R22 fallback behavior and document the plan evidence. A dedicated snapshot architecture belongs in a separate future release, not as an unmeasured R22 expansion.
