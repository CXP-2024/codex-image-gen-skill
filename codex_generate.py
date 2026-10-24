"""Generate images with Codex CLI's built-in image_gen tool and copy them out of $CODEX_HOME.

Codex saves built-in images under <CODEX_HOME>/generated_images/<session id>/exec-*.png and its
image tool takes no size/quality/seed arguments, so this script only forwards the prompt (plus
optional reference images) and collects whatever new files appear for that session.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
GENERATED = CODEX_HOME / "generated_images"
INSTRUCTION = (
    "Use your built-in image_gen tool (not the CLI fallback, not SVG/HTML) to generate exactly {count} "
    "separate image(s) from the prompt below, one image_gen call per image. Pass the prompt through "
    "faithfully; do not add characters, objects or text it does not ask for. Do not run shell commands "
    "and do not copy or move files. When done, reply only with the saved file path(s).\n\nPrompt:\n{prompt}"
)


def snapshot():
    return {p: p.stat().st_mtime for p in GENERATED.rglob("*") if p.is_file()} if GENERATED.exists() else {}


def session_ids(jsonl):
    ids = set()
    for line in jsonl.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        stack = [event]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                for key, value in item.items():
                    if key in ("thread_id", "session_id", "conversation_id") and isinstance(value, str):
                        ids.add(value)
                    stack.append(value)
            elif isinstance(item, list):
                stack.extend(item)
    return ids


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--job", help="UTF-8 JSON with prompt, count, images, prefix")
    parser.add_argument("--prompt")
    parser.add_argument("--count", type=int)
    parser.add_argument("--image", action="append", default=None, help="reference image (repeatable)")
    parser.add_argument("--prefix", help="output name prefix relative to --output-root")
    parser.add_argument("--output-root", default=r"H:\ComfyUI-latest\output")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    job = {"count": 1, "images": [], "prefix": "codex/test"}
    if args.job:
        job.update(json.loads(Path(args.job).read_text(encoding="utf-8-sig")))
    for key in ("prompt", "count", "prefix"):
        if getattr(args, key) is not None:
            job[key] = getattr(args, key)
    if args.image is not None:
        job["images"] = args.image
    if not job.get("prompt"):
        sys.exit("prompt is required (--prompt or a job file)")

    codex = shutil.which("codex")
    if not codex:
        sys.exit("codex CLI not found on PATH")
    before = snapshot()
    workdir = tempfile.mkdtemp(prefix="codex-imagegen-")
    cmd = [codex, "exec", "--skip-git-repo-check", "--json", "-s", "read-only", "-C", workdir]
    for image in job["images"]:
        cmd += ["-i", str(Path(image).resolve())]
    cmd.append("-")
    started = time.time()
    try:
        run = subprocess.run(cmd, input=INSTRUCTION.format(count=job["count"], prompt=job["prompt"]),
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=args.timeout)
    except subprocess.TimeoutExpired:
        sys.exit(f"codex exec timed out after {args.timeout}s")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    new = sorted((p for p, m in snapshot().items() if p not in before or m > before[p]),
                 key=lambda p: p.stat().st_mtime)
    ids = session_ids(run.stdout)
    mine = [p for p in new if p.parent.name in ids] or new
    if not mine:
        sys.exit(f"no new image under {GENERATED} (exit {run.returncode}):\n{run.stderr[-2000:]}")

    target = Path(args.output_root, job["prefix"])
    target.parent.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, source in enumerate(mine, 1):
        dest = target.parent / f"{target.name}_{i:05d}_{source.suffix}"
        n = i
        while dest.exists():
            n += 1
            dest = target.parent / f"{target.name}_{n:05d}_{source.suffix}"
        shutil.copy2(source, dest)
        paths.append(str(dest))
    print(json.dumps({"backend": "codex", "session": sorted(ids), "seconds": round(time.time() - started),
                      "sources": [str(p) for p in mine], "images": paths}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
