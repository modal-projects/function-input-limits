# HTTP server: requests go through Modal's proxy, not the Function input system.
#   modal deploy server/app.py
import asyncio
import threading

import modal

image = modal.Image.debian_slim().uv_pip_install("fastapi", "uvicorn")
app = modal.App("demo-server", image=image)

with image.imports():
    from fastapi import FastAPI

    api = FastAPI()

    @api.post("/work")
    async def work(body: dict) -> dict:
        await asyncio.sleep(body["seconds"])  # stands in for 1-10 s of real work
        return {"seconds": body["seconds"]}


# unauthenticated for the example only; production callers send a Proxy Token.
@app.server(port=8000, target_concurrency=1000, min_containers=2, max_containers=16, unauthenticated=True)
class WorkerServer:
    @modal.enter()
    def start(self):
        import uvicorn

        threading.Thread(target=lambda: uvicorn.run(api, host="0.0.0.0", port=8000), daemon=True).start()
