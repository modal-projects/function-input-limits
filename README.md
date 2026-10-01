# Scaling a Modal Function to more inputs

A Function called with `.remote()` accepts 200 inputs/s and queues at most 2,000
([limits](https://modal.com/docs/guide/function-invocation-methods#scalability)).
Past that, callers see `Input rate limit exceeded` or `reached pending input queue limit`.

Each folder shows one way past the limits: an `app.py` to deploy and a `caller.py` that
makes 1,000 concurrent calls. The work is a 1-10 s sleep.

## 1. `spawn` instead of `remote`: [`spawn/`](spawn/)

Async calls are accepted at up to 1,500 inputs/s, with a queue of 1 million. The
Function stays the same. Only the caller changes:

```python
# before
result = await worker.work.remote.aio(x)

# after
call = await worker.work.spawn.aio(x)
result = await call.get.aio()
```

Acceptance is not throughput. Above about 200 inputs/s per Function, spawned inputs
still get accepted, but they wait longer to start (see [Measured](#measured)). Spawned
calls also keep running if the caller exits. Call `call.cancel()` for results you no
longer need.

## 2. One app copy per caller: [`copies/`](copies/)

Limits apply per Function, so N deployed copies give N times the limits. No code change:

```bash
for i in 0 1 2 3 4 5 6 7; do modal deploy --name demo-copy-$i copies/app.py; done
```

```python
worker = modal.Cls.from_name(f"demo-copy-{i}", "Worker")()
```

## 3. Many items per input: [`batching/`](batching/)

When the caller already has a list of work, send it in chunks. One input then carries
32 items:

```python
@modal.method()
async def work_many(self, xs: list[float]) -> list[float]: ...
```

```python
chunks = [xs[i : i + 32] for i in range(0, len(xs), 32)]
results = await asyncio.gather(*(worker.work_many.remote.aio(c) for c in chunks))
```

Each chunk finishes when its slowest item does. If one item fails, the whole chunk fails.

## 4. An HTTP server: [`server/`](server/)

`@app.server()` requests go through Modal's HTTP proxy, not the input queue, so there is
no input limit. The Function becomes a web app:

```python
@app.server(port=8000, cpu=1, target_concurrency=1000)
class WorkerServer:
    @modal.enter()
    def start(self):
        threading.Thread(target=lambda: uvicorn.run(api, host="0.0.0.0", port=8000), daemon=True).start()
```

```python
async with session.post("/work", json={"seconds": x}) as r:  # aiohttp
    result = (await r.json())["seconds"]
```

The client handles serialization, retries (503 when no container is ready) and timeouts.
Use aiohttp for high concurrency. With httpx, one process with 1,000 requests in flight
got about a third of the throughput.
Production callers also send a [Proxy Token](https://modal.com/docs/guide/webhook-proxy-auth).

## Which one

| | Function changes | Caller changes | Limit |
|---|---|---|---|
| `spawn` | No | One line | 1,500/s accepted, starts slow down above about 200/s |
| App copies | No | Look up copy N | 200/s × N copies |
| Batching | Takes a list | Send chunks | 200/s × chunk size |
| Server | Becomes a web app | HTTP client | No input limit |

Start with `spawn`: it is a one-line change. If its start delay matters, deploy app
copies. Batching fits when the caller already has a list. A Server fits when latency
matters and the client can own retries. In every case, throughput is also capped by compute: at most
`max_containers × inputs per container ÷ call duration` calls per second.

## Measured

8 clients × 1,000 calls of 1-10 s, all starting at once, for 60-120 s:

| | Load from | Calls/s | Ideal | Added latency p50 / p90 / p99 | Errors |
|---|---|---|---|---|---|
| `spawn` | Laptop | 755 | 1,455 | 0.67 / 21.7 / 28.1 s | 0 |
| App copies (8) | Laptop | 1,338 | 1,455 | 0.27 / 2.56 / 6.86 s | 0 |
| Batching (chunks of 32, one round of 1,000 at a time) | Laptop | 800 | about 800 | 0.26 / 3.58 / 4.17 s | 0 |
| Server | Modal container (k6) | 1,450 | 1,455 | 0.09 / 0.23 / 1.59 s | 0 |

Ideal is the rate with no overhead: calls in flight ÷ mean call duration. Each client
waits for its calls, so `spawn`'s start delay also lowers its calls/s. Batching's ideal is
lower because each round waits for its slowest call.

Opening 8,000 HTTP connections at once from one laptop failed with connect timeouts. The
same burst from a Modal container had no errors, so test a Server burst from the cloud.

## Run

```bash
pip install -r requirements.txt
modal deploy spawn/app.py
python spawn/caller.py        # prints "1000 calls in N s"
```

[`loadtest/`](loadtest/) runs sustained load:

```bash
python loadtest/run.py spawn --clients 8 --concurrency 1000 --warmup 0   # also copies, batching, server
modal run loadtest/k6_in_modal.py --vus 8000                             # Server burst, from a Modal container
```

Stop the apps when done. They keep a warm container:

```bash
for app in demo-copy-{0..7} demo-spawn demo-batch demo-server; do modal app stop --yes $app; done
```
