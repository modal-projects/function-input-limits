# Function input limits: four ways past them

Many callers making many short `.remote()` calls to one Modal Function can hit two
platform limits:

- `Input rate limit (200/s) exceeded for function fu-...`
- `Function fu-... reached pending input queue limit (2000)`

This repo shows four ways to get past them, each as a small deployable app plus the
simplest caller that uses it. The example workload is 8 clients, each making 1,000
concurrent calls that take 1-10 s. That is about 800-8,000 calls/s, depending on the
call duration.

## The limits

From the [Function invocation methods guide](https://modal.com/docs/guide/function-invocation-methods#scalability):

| | Synchronous (`.remote`, `.map`) | Asynchronous (`.spawn`, `.spawn_map`) |
|---|---|---|
| Rate | 200/s | 1,500/s |
| Inputs waiting for a container | 2,000 | 1 million |
| Inputs in the system (queued or running) | 25,000 | not stated |

Limits apply per Function. Each input counts once: a `.map()` item is an input, and so
is each call to a Function decorated with
[`@modal.batched`](https://modal.com/docs/guide/dynamic-batching). Neither of those
reduces the count.

## The approaches

| | [App copies](copies/) | [`spawn` + `get`](spawn/) | [Caller-side batching](batching/) | [`app.server()`](server/) |
|---|---|---|---|---|
| **Callee change** | None. Deploy N times with `--name` | None | Method takes and returns a list and runs the items in parallel | Rewrite as an HTTP app (for example FastAPI + uvicorn) in `@app.server` |
| **Caller change** | Each client looks up its own copy | `.spawn.aio()` then `.get.aio()` | Send lists in chunks, flatten the results | HTTP client, URL lookup, Proxy Token, 503 retry |
| **Request shape** | One input per call | One input per call | One input per chunk | One HTTP request per call |
| **Arguments** | Any Python object (cloudpickle) | Any Python object | Any Python object, as a list | JSON or bytes you serialize yourself |
| **Rate limit** | 200/s per copy | 1,500/s | 200/s inputs, times the chunk size in tasks | None |
| **Queue limit** | 2,000 per copy | 1 million | 2,000 inputs, times the chunk size in tasks | None: 503 when no container is ready |
| **Latency** | Normal `.remote` | Higher: the asynchronous path is durable | Each item waits for the slowest in its chunk | Lowest |
| **CPU cost** | Unchanged | Unchanged | Higher for CPU-bound work: finished cores idle until the chunk's slowest item ends | Unchanged, if the handler moves CPU work off the event loop |
| **Failures and retries** | Per call, with the Function's `retries` | Per call, with `retries` | One failing item fails the chunk, and `retries` reruns all of it | No Modal retries or timeouts. The client handles both |
| **If the caller dies** | Call cancelled within about 2 min | Call keeps running and its result is kept for 7 days. Cancel with `fc.cancel()` | Cancelled | Request dropped |
| **Operations** | N deploys, N autoscalers, N warm pools | One deploy | One deploy | One deploy, autoscaled on `target_concurrency`, plus token management |
| **Modal features kept** | All | All | All, but per chunk | No input queue, retries, per-call timeouts or per-call records in the dashboard |

**Where to start.** `spawn` is the smallest change: one line in the caller and nothing
in the Function. App copies also need no code change and work straight away. A Server
is the long-term fit when latency matters, but it is a rewrite, and the client takes
over retries and timeouts. Batching changes both sides and fits best when the caller
already has a list of work to submit together.

**Compute is a separate ceiling.** None of these changes the CPU a call needs.
Completed calls per second are at most `max_containers × concurrent inputs per
container ÷ mean call duration`. Check that number before raising a rate limit. For
example, 100 containers × 10 concurrent inputs ÷ 5 s is 200 calls/s.

## Run the examples

Requires Python 3.11+ and a Modal account.

```bash
pip install -r requirements.txt

# deploy
for i in 0 1 2 3 4 5 6 7; do modal deploy --name demo-copy-$i copies/app.py; done
modal deploy spawn/app.py
modal deploy batching/app.py
modal deploy server/app.py

# one client's worth of calls (1,000), with timing
CLIENT_IDX=0 python copies/caller.py
python spawn/caller.py
python batching/caller.py
python server/caller.py
```

The Function in every app sleeps 1-10 s in place of real work. Swap in your own
function body to test your workload.

## Load test

[`loadtest/`](loadtest/) runs sustained load: N clients as separate processes, M
concurrent calls each. It reports completed calls/s, overhead (latency minus the
call's own duration) and errors grouped by message.

```bash
python loadtest/run.py fake     --clients 8 --concurrency 1000   # no Modal; checks the harness
python loadtest/run.py copies   --clients 8 --concurrency 1000
python loadtest/run.py spawn    --clients 8 --concurrency 1000
python loadtest/run.py server   --clients 8 --concurrency 1000
python loadtest/run.py batching --clients 8 --concurrency 1000   # lockstep rounds, chunks of 32
```

The demo Functions sleep instead of using CPU. The load test therefore measures Modal's
input and routing limits, not compute capacity.

## Clean up

The apps keep warm containers (`min_containers`) until stopped:

```bash
for app in demo-copy-{0..7} demo-spawn demo-batch demo-server; do modal app stop --yes $app; done
```

The Server example sets `unauthenticated=True` to keep the test simple. Production
callers should send a [Proxy Token](https://modal.com/docs/guide/webhook-proxy-auth)
instead.
