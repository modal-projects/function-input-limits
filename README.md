# Scaling a Modal Function to more inputs

A Function called with `.remote()` accepts 200 inputs/s and queues at most 2,000
([limits](https://modal.com/docs/guide/function-invocation-methods#scalability)).
Past that, callers see `Input rate limit exceeded` or `reached pending input queue limit`.

Each folder shows one way past the limits: an `app.py` to deploy and a `caller.py` that
makes 1,000 concurrent calls. The work is a 1-10 s sleep.

Three terms used below:

- **Input:** one call to a Function. A batched call that carries a list is one input.
- **Accepted vs started:** Modal first accepts an input into its queue, then starts it
  on a container. The two can have different limits. Both are per Function.
- **Calls per container:** one container runs several calls at once
  (`@modal.concurrent(max_inputs=N)`). Modal adds containers as calls pile up, up to
  `max_containers`.

## Starting point

A Function that runs several calls per container, called once per item:

```python
# app.py
@app.cls()
@modal.concurrent(max_inputs=500)
class Worker:
    @modal.method()
    async def work(self, x: float) -> float: ...
```

```python
# caller.py
worker = modal.Cls.from_name("my-app", "Worker")()
results = await asyncio.gather(*(worker.work.remote.aio(x) for x in xs))
```

Each approach below changes one side of this.

## 1. `spawn` instead of `remote`: [`spawn/`](spawn/)

The Function stays the same. The caller spawns each call, then waits for its result:

```python
# caller.py
async def call(x):
    fc = await worker.work.spawn.aio(x)
    return await fc.get.aio()

results = await asyncio.gather(*(call(x) for x in xs))
```

Spawned inputs are accepted at up to 1,500/s, but they start more slowly: above about
200/s per Function, extra inputs wait instead of failing (see [Measured](#measured)).
Spawned calls also keep running if the caller exits. Call `fc.cancel()` for results you
no longer need.

## 2. One app copy per caller: [`copies/`](copies/)

Limits apply per Function, so N deployed copies give N times the limits. The code stays
the same. Deploy it N times under different names:

```bash
for i in 0 1 2 3 4 5 6 7; do modal deploy --name demo-copy-$i copies/app.py; done
```

```python
# caller.py, for caller number i
worker = modal.Cls.from_name(f"demo-copy-{i}", "Worker")()
results = await asyncio.gather(*(worker.work.remote.aio(x) for x in xs))
```

## 3. Many items per input: [`batching/`](batching/)

The Function takes a list and runs its items concurrently. The caller sends chunks, so
1,000 items become 32 inputs:

```python
# app.py
@modal.method()
async def work_many(self, xs: list[float]) -> list[float]:
    return list(await asyncio.gather(*(do_work(x) for x in xs)))
```

```python
# caller.py
chunks = [xs[i : i + 32] for i in range(0, len(xs), 32)]
results = await asyncio.gather(*(worker.work_many.remote.aio(c) for c in chunks))
results = [r for chunk in results for r in chunk]
```

Each chunk finishes when its slowest item does. If one item fails, the whole chunk fails.

## 4. An HTTP server: [`server/`](server/)

The Function becomes a web app. Requests go through Modal's HTTP proxy, not the input
queue, so there is no input limit:

```python
# app.py
api = FastAPI()

@api.post("/work")
async def work(body: dict) -> dict: ...

@app.server(port=8000, cpu=1, target_concurrency=1000)
class WorkerServer:
    @modal.enter()
    def start(self):
        threading.Thread(target=lambda: uvicorn.run(api, host="0.0.0.0", port=8000), daemon=True).start()
```

```python
# caller.py
url = modal.Server.from_name("demo-server", "WorkerServer").get_url()

async with aiohttp.ClientSession(base_url=url) as session:
    async def call(x):
        async with session.post("/work", json={"seconds": x}) as r:
            return (await r.json())["seconds"]

    results = await asyncio.gather(*(call(x) for x in xs))
```

The client handles serialization, retries (503 when no container is ready) and timeouts.
Use aiohttp for high concurrency. With httpx, one process with 1,000 requests in flight
got about a third of the throughput. Production callers also send a
[Proxy Token](https://modal.com/docs/guide/webhook-proxy-auth).

## Which one

| | Function changes | Caller changes | Accepted | Started | Calls per container here |
|---|---|---|---|---|---|
| `spawn` | No | One line | 1,500/s | Lower, extra inputs wait (589/s in the test below) | 500 |
| App copies | No | Look up copy N | 200/s per copy | Same as accepted | 500 |
| Batching | Takes a list | Send chunks | 200 inputs/s × chunk size | Same as accepted | 50 chunks of 32 |
| Server | Becomes a web app | HTTP client | No input limit, 503 when no container is ready | Containers × requests per container | About 1,000 (`target_concurrency`) |

Workspaces can have different rate limits from these defaults.

Start with `spawn`: it is a one-line change. If its start delay matters, deploy app
copies. Batching fits when the caller already has a list. A Server fits when latency
matters and the client can own retries. In every case, throughput is also capped by compute: at most
`max_containers × inputs per container ÷ call duration` calls per second.

## Measured

8 clients × 1,000 calls of 1-10 s, all starting at once, for 60 s, called from a Modal
container in us-east ([`loadtest/run_in_modal.py`](loadtest/run_in_modal.py)):

| | Calls/s | Ideal | First 8,000 calls back after | Added latency p50 / p90 / p99 | Containers | Errors |
|---|---|---|---|---|---|---|
| `spawn` | 589 | 1,455 | 34.6 s | 9.11 / 13.6 / 19.8 s | 12 | 0 |
| App copies (8) | 1,391 | 1,455 | 18.2 s | 0.20 / 1.48 / 5.65 s | 19 | 0 |
| Batching (chunks of 32, one round of 1,000 at a time) | 800 | about 800 | 16.7 s | 0.21 / 2.52 / 5.12 s | 6 | 0 |
| Server | 1,401 | 1,455 | 15.6 s | 0.12 / 0.34 / 5.43 s | 8 | 0 |

Ideal is the rate with no overhead: calls in flight ÷ mean call duration. With no
overhead, the first calls are all back after about 10 s. Each client waits for its calls,
so `spawn`'s start delay also lowers its calls/s. Batching's ideal is lower because each
round waits for its slowest call.

Load a Server from the cloud: opening 8,000 HTTP connections at once from one laptop
failed with connect timeouts.

## Run

```bash
pip install -r requirements.txt
modal deploy spawn/app.py
python spawn/caller.py        # prints "1000 calls in N s"
```

[`loadtest/`](loadtest/) runs sustained load:

```bash
modal run loadtest/run_in_modal.py                                       # all four, from a Modal container
python loadtest/run.py spawn --clients 8 --concurrency 1000 --warmup 0   # one approach, from this machine
modal run loadtest/k6_in_modal.py --vus 8000                             # Server burst with k6, from Modal
```

Stop the apps when done. They keep a warm container:

```bash
for app in demo-copy-{0..7} demo-spawn demo-batch demo-server; do modal app stop --yes $app; done
```
