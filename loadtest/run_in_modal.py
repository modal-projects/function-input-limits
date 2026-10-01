# Run loadtest/run.py from a Modal container, so every approach is called from inside Modal.
#   modal run loadtest/run_in_modal.py --modes copies,spawn,batching,server
import subprocess
from pathlib import Path

import modal

image = (
    modal.Image.debian_slim()
    .uv_pip_install("modal", "aiohttp")
    .add_local_dir(Path(__file__).parent, "/root/loadtest", ignore=["__pycache__"])
)
app = modal.App("demo-loadtest", image=image)


@app.function(cpu=16, memory=16384, timeout=900, region="us-east")
def load(mode: str, args: list[str]) -> str:
    cmd = ["python", "run.py", mode, *args]
    result = subprocess.run(cmd, cwd="/root/loadtest", capture_output=True, text=True)
    return result.stdout + result.stderr[-2000:]


@app.local_entrypoint()
def main(modes: str = "copies,spawn,batching,server", args: str = "--clients 8 --concurrency 1000 --duration 60"):
    for mode in modes.split(","):
        print(load.remote(mode, [*args.split(), "--warmup", "0", "--ramp", "0"]))
