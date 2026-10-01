"""Load harness for the examples.

Simulates N clients, one process each, with M concurrent calls per client, in one of
two shapes:

- independent: each of the M call loops runs on its own, calling `call(seconds)` for one
  1-10 s task at a time.
- lockstep: each client runs rounds of M tasks and calls `call(list_of_seconds)` once per
  round.

Reports completed calls/s, overhead, and errors. Overhead is latency minus the task's own
duration, or for lockstep, minus the longest task in the round.
"""

import argparse
import asyncio
import collections
import multiprocessing as mp
import random
import statistics
import time


async def _client(make_call, idx, args, out):
    call = await make_call(idx)
    overheads, errors, done = [], collections.Counter(), 0
    t_start = time.monotonic()
    stop_at = t_start + args.duration
    warm_until = t_start + args.warmup
    first_done = []  # seconds from start until each call loop's (or the first round's) first success

    async def rounds():
        nonlocal done
        while time.monotonic() < stop_at:
            round_ = [random.uniform(1, 10) for _ in range(args.concurrency)]
            t0 = time.monotonic()
            try:
                await call(round_)
                if not first_done:
                    first_done.append(time.monotonic() - t_start)
                if t0 > warm_until:
                    done += len(round_)
                    overheads.append(time.monotonic() - t0 - max(round_))
            except Exception as e:
                errors[f"{type(e).__name__}: {str(e)[:90]}"] += 1
                await asyncio.sleep(1)

    async def loop():
        nonlocal done
        await asyncio.sleep(random.uniform(0, args.ramp))  # 0: every call starts at once
        first = True
        while time.monotonic() < stop_at:
            s = random.uniform(1, 10)
            t0 = time.monotonic()
            try:
                await call(s)
                if first:
                    first_done.append(time.monotonic() - t_start)
                    first = False
                if t0 > warm_until:
                    done += 1
                    overheads.append(time.monotonic() - t0 - s)
            except Exception as e:
                errors[f"{type(e).__name__}: {str(e)[:90]}"] += 1
                await asyncio.sleep(1)

    if args.lockstep:
        await rounds()
    else:
        await asyncio.gather(*(loop() for _ in range(args.concurrency)))
    if close := getattr(call, "close", None):
        await close()
    out.put((done, overheads, dict(errors), first_done))


def _proc(make_call, idx, args, out):
    asyncio.run(_client(make_call, idx, args, out))


def _pct(xs, p):
    return statistics.quantiles(xs, n=100, method="inclusive")[p - 1] if len(xs) >= 2 else float("nan")


def run(make_call, name: str, lockstep: bool = False):
    """`make_call(idx)` returns the client's async call; it must be a module-level function.

    The call takes one float, or a list of floats when `lockstep` is set.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--clients", type=int, default=8)
    ap.add_argument("--concurrency", type=int, default=1000)
    ap.add_argument("--duration", type=float, default=120)
    ap.add_argument("--warmup", type=float, default=20)
    ap.add_argument("--ramp", type=float, default=0, help="spread call-loop starts over this many seconds")
    args = ap.parse_args()
    args.lockstep = lockstep

    out = mp.Queue()
    procs = [mp.Process(target=_proc, args=(make_call, i, args, out)) for i in range(args.clients)]
    for p in procs:
        p.start()
    results = [out.get() for _ in procs]
    for p in procs:
        p.join()

    measured = args.duration - args.warmup
    total = sum(r[0] for r in results)
    overheads = [o for r in results for o in r[1]]
    errors = collections.Counter()
    for r in results:
        errors.update(r[2])
    shape = "lockstep" if lockstep else "independent"
    print(f"{name} ({shape}): clients={args.clients} concurrency={args.concurrency} measured={measured:.0f}s")
    print(f"completed calls: {total} ({total / measured:.0f}/s)")
    firsts = [f for r in results for f in r[3]]
    expected = args.clients * (1 if lockstep else args.concurrency)
    if firsts:
        print(f"first calls returned: {len(firsts)}/{expected}, last one after {max(firsts):.1f}s")
    if overheads:
        print(
            f"overhead s: p50={_pct(overheads, 50):.2f} p90={_pct(overheads, 90):.2f} "
            f"p99={_pct(overheads, 99):.2f} max={max(overheads):.2f}"
        )
    print(f"errors: {sum(errors.values())}")
    for k, v in errors.most_common(10):
        print(f"  {v:6d}  {k}")
