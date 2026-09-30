"""Sustained load against the example apps: N clients x M concurrent calls each.

python loadtest/run.py copies   --clients 8 --concurrency 1000
python loadtest/run.py spawn    --clients 8 --concurrency 1000
python loadtest/run.py server   --clients 8 --concurrency 1000
python loadtest/run.py batching --clients 8 --concurrency 1000   # lockstep rounds, chunks of 32
python loadtest/run.py fake     --clients 8 --concurrency 1000   # no Modal; checks the harness
"""

import asyncio
import sys

from loadgen import run


async def copies(idx: int):
    import modal

    return modal.Cls.from_name(f"demo-copy-{idx}", "Worker")().work.remote.aio


async def spawn(idx: int):
    import modal

    worker = modal.Cls.from_name("demo-spawn", "Worker")()

    async def call(seconds: float) -> float:
        fc = await worker.work.spawn.aio(seconds)
        return await fc.get.aio()

    return call


async def server(idx: int):
    import httpx
    import modal

    url = await modal.Server.from_name("demo-server", "WorkerServer").get_url.aio()
    client = httpx.AsyncClient(base_url=url, timeout=60, limits=httpx.Limits(max_connections=2000))

    async def call(seconds: float) -> float:
        for attempt in range(5):
            r = await client.post("/work", json={"seconds": seconds})
            if r.status_code != 503:
                r.raise_for_status()
                return r.json()["seconds"]
            await asyncio.sleep(0.2 * 2**attempt)
        raise RuntimeError("503 after 5 attempts")

    return call


async def batching(idx: int):
    import modal

    worker = modal.Cls.from_name("demo-batch", "Worker")()

    async def call_all(seconds: list[float]) -> list[float]:
        chunks = [seconds[i : i + 32] for i in range(0, len(seconds), 32)]
        results = await asyncio.gather(*(worker.work_many.remote.aio(c) for c in chunks))
        return [r for rs in results for r in rs]

    return call_all


async def fake(idx: int):
    async def call(seconds: float) -> float:
        await asyncio.sleep(seconds)
        return seconds

    return call


if __name__ == "__main__":
    mode = sys.argv.pop(1)
    make_call = {"copies": copies, "spawn": spawn, "server": server, "batching": batching, "fake": fake}[mode]
    run(make_call, mode, lockstep=mode == "batching")
