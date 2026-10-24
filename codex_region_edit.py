"""Fix one small object (a hand, a prop) in a finished image with Codex image editing, keeping the style.

The square `box` is cropped and upscaled to 1024, Codex edits it from the instruction (plus optional reference
images), the result is color-matched to the original crop (MKL), scaled back, and pasted only inside `mask`
(an ellipse or polygon in image coordinates) with a feathered edge; everything outside keeps its original pixels.
The Codex result is cached, so the mask can be adjusted and pasted again without another call (~45 s, uses quota).

Job JSON:
{"image": "H:/.../in.png", "out": "H:/.../out.png", "box": [x0, y0, x1, y1],
 "prompt": "Fix only the white-gloved hand ...", "refs": ["H:/.../ref.png"], "ref_role": "shape" | "style" | "both",
 "mask": {"ellipse": [cx, cy, rx, ry]} or {"polygon": [[x, y], ...]}, "feather": 6}
Writes <out>_check.png: original crop / Codex result / pasted crop.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import generate  # noqa: E402

FRAME = ("Edit the FIRST attached image, a crop of a finished anime illustration. {instruction} Change nothing else: "
         "keep every other line, color, shape and texture in the crop exactly as it is. Keep the illustration's own "
         "hand-drawn style: the same line weight, flat cel shading, soft colors, lighting and haze; do not make the "
         "edited part sharper, more saturated or more detailed than its surroundings. {refs}Output one square image "
         "with exactly the same framing as the first image.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", required=True)
    ap.add_argument("--redo", action="store_true", help="call Codex again even if a cached result exists")
    a = ap.parse_args()
    job = json.loads(Path(a.job).read_text(encoding="utf-8-sig"))
    original = Image.open(job["image"]).convert("RGB")
    x0, y0, x1, y1 = job["box"]
    crop = original.crop((x0, y0, x1, y1))
    out = Path(job["out"])
    work = out.parent / (out.stem + "_codex_work")
    work.mkdir(parents=True, exist_ok=True)
    crop_path = work / "crop.png"
    crop.resize((1024, 1024), Image.LANCZOS).save(crop_path)
    cached = work / "codex.png"
    if cached.exists() and not a.redo:
        edited = Image.open(cached).convert("RGB")
    else:
        refs = job.get("refs", [])
        note = {"shape": "The other attached images are references for what the edited part should look like; copy "
                         "only the shape from them, never their style. ",
                "style": "The other attached images are crops of the same illustration by the same artist: render the "
                         "edited part exactly in their drawing style (line weight and color, flat color blocks, "
                         "shadow shapes, color fringing), but do not copy their anatomy or pose. ",
                "both": "The other attached images show the same artist's style and the wanted shape: copy both the "
                        "shape and the drawing style from them. "}[job.get("ref_role", "shape")] if refs else ""
        cmd = [sys.executable, "-I", str(HERE / "codex_generate.py"),
               "--prompt", FRAME.format(instruction=job["prompt"], refs=note),
               "--image", str(crop_path), "--prefix", f"codex_region/{out.stem}"]
        for r in refs:
            cmd += ["--image", r]
        run = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if run.returncode != 0:
            sys.exit(f"codex failed: {run.stderr[-1500:]}")
        edited = Image.open(json.loads(run.stdout)["images"][0]).convert("RGB")
        edited.save(cached)
    edited = edited.resize(crop.size, Image.LANCZOS)
    if job.get("color_match", 1.0):
        ref = np.asarray(crop, np.float32) / 255
        arr = np.asarray(edited, np.float32) / 255
        arr = (arr + job.get("color_match", 1.0) * (generate.mkl_transfer(arr, ref) - arr)).clip(0, 1)
        edited = Image.fromarray((arr * 255).round().astype(np.uint8))

    mask = Image.new("L", crop.size, 0)
    m = job["mask"]
    if "ellipse" in m:
        cx, cy, rx, ry = m["ellipse"]
        ImageDraw.Draw(mask).ellipse((cx - rx - x0, cy - ry - y0, cx + rx - x0, cy + ry - y0), fill=255)
    else:
        ImageDraw.Draw(mask).polygon([(x - x0, y - y0) for x, y in m["polygon"]], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(job.get("feather", 6)))
    result = original.copy()
    result.paste(edited, (x0, y0), mask)
    out.parent.mkdir(parents=True, exist_ok=True)
    result.save(out)

    tiles = [crop, edited, result.crop((x0, y0, x1, y1))]
    sheet = Image.new("RGB", (3 * 410, 400), "white")
    for i, t in enumerate(tiles):
        sheet.paste(t.resize((400, 400), Image.LANCZOS), (i * 410, 0))
    sheet.save(out.parent / (out.stem + "_check.png"))
    print(out)


if __name__ == "__main__":
    main()
