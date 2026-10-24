"""Fix Furina's eyes with Codex image editing, pasting back only the iris (user-approved method, 2026-10-22).

For each eye: crop a square around it, upscale to 1024, send it to Codex together with the official eye
(refs/furina_eye_<kind>.png) and, by default, a sheet of eyes in the kieed style (refs/kieed_eye_style.png).
The Codex result is scaled back and pasted ONLY inside the drawn iris area of the original (eye_fix.iris_region),
so lids, lashes, hair and everything else keep their original pixels. One Codex call per eye (~45 s, uses quota).

Job JSON:
{"image": "H:\\...\\in.png", "out": "H:\\...\\out.png", "style": true,
 "style_ref": "optional path; default refs/kieed_eye_style.png", "render": "optional style text for that ref",
 "eyes": [{"cx": 1380, "cy": 756, "r": 19, "ry": 15, "kind": "light"}, {"cx": 1484, "cy": 810, "r": 17, "kind": "dark"}]}
kind is by HER eye: light = her right eye (viewer's left when she faces us), dark = her left eye. In a mirror
reflection the sides swap. "angle" (head tilt, counter-clockwise degrees) is derived from the two eyes when both
are given. A check sheet (original / Codex / pasted, per eye) is written next to the output.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import eye_fix  # noqa: E402

DESIGN = {
    "light": "a pale luminous sky-blue / cyan iris with fine radial streaks and a thin dark navy outer ring; the pupil "
             "is a slender dark violet-blue water droplet pointing up toward her forehead (following the tilt of her "
             "head), set high in the iris near its top edge; a soft white highlight at the bottom of the iris",
    "dark": "a deep violet-blue indigo iris with only a very thin pinkish-violet line along its lowest edge and a dark "
            "outer ring; the pupil is a slender light-cyan water droplet pointing up toward her forehead (following "
            "the tilt of her head), set high in the iris; a few tiny white glints",
}
PROMPT = ("Edit the FIRST attached image (a crop of an anime illustration showing one eye). The SECOND image is the "
          "official character art of the same eye: use it ONLY for the eye's design. {third}Change only the iris and "
          "pupil of the eye in the first image so that its design matches the second image: {design}. {render}Keep "
          "the eyelids, eyelashes, eye white, skin, the hair (including any translucent strands in front of the eye), "
          "the framing, and the eye's size and position exactly the same. Output one square image with the same "
          "framing as the first image.")
THIRD = ("The THIRD image shows how the illustrator of the first image draws eyes: use it ONLY for the rendering "
         "style, not for the pupil shape. ")
RENDER = ("Render the new iris exactly in the illustrator's style from the third image: flat cel shading with a darker "
          "upper half and a lighter lower half of the iris separated by a soft but clear edge, bold dark outlines "
          "around the iris and the pupil, a few small round white highlights, sparse simple radial strokes, and no "
          "glossy gradients or glow. ")
PLAIN_RENDER = "Keep the first image's hand-drawn anime style, line weight and soft colors; do not copy the reference's art style. "


def codex_edit(crop_path, kind, style, prefix, style_ref=None, render=None):
    prompt = PROMPT.format(third=THIRD if style else "", design=DESIGN[kind],
                           render=(render or RENDER) if style else PLAIN_RENDER)
    cmd = [sys.executable, "-I", str(HERE / "codex_generate.py"), "--prompt", prompt,
           "--image", str(crop_path), "--image", str(HERE / "refs" / f"furina_eye_{kind}.png"), "--prefix", prefix]
    if style:
        cmd += ["--image", str(style_ref or HERE / "refs" / "kieed_eye_style.png")]
    run = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if run.returncode != 0:
        sys.exit(f"codex failed: {run.stderr[-1500:]}")
    return Image.open(json.loads(run.stdout)["images"][0]).convert("RGB")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", required=True)
    ap.add_argument("--redo", action="store_true", help="call Codex again even if a cached result exists")
    a = ap.parse_args()
    job = json.loads(Path(a.job).read_text(encoding="utf-8-sig"))
    original = Image.open(job["image"]).convert("RGB")
    base = original.copy()
    out = Path(job["out"])
    work = out.parent / (out.stem + "_codex_work")
    work.mkdir(parents=True, exist_ok=True)
    eyes = job["eyes"]
    kinds = {e["kind"]: e for e in eyes}
    if "light" in kinds and "dark" in kinds and not job.get("mirror"):
        lt, dk = kinds["light"], kinds["dark"]
        tilt = float(np.degrees(np.arctan2(-(dk["cy"] - lt["cy"]), dk["cx"] - lt["cx"])))
    elif len(eyes) == 2:  # mirror reflection: dark is on the viewer's left
        e0, e1 = sorted(eyes, key=lambda e: e["cx"])
        tilt = float(np.degrees(np.arctan2(-(e1["cy"] - e0["cy"]), e1["cx"] - e0["cx"])))
    else:
        tilt = 0.0
    rows = []
    for n, eye in enumerate(eyes):
        eye.setdefault("angle", round(tilt, 1))
        eye.setdefault("ry", eye["r"] * 1.05)
        half = int(max(job.get("context", 3.2) * max(eye["r"], eye["ry"]), job.get("min_half", 80)))
        box = (eye["cx"] - half, eye["cy"] - half, eye["cx"] + half, eye["cy"] + half)
        crop_path = work / f"eye{n}_crop.png"
        original.crop(box).resize((1024, 1024), Image.LANCZOS).save(crop_path)
        cached = work / f"eye{n}_codex.png"
        if cached.exists() and not a.redo:  # rerun only the paste step (e.g. after adjusting "add"/"cut")
            edited = Image.open(cached).convert("RGB")
        else:
            edited = codex_edit(crop_path, eye["kind"], job.get("style", True), f"codex_eye/{out.stem}_eye{n}",
                                job.get("style_ref"), job.get("render"))
            edited.save(cached)
        # Paste only inside the drawn iris of the original.
        rhalf = int(max(eye["r"], eye["ry"]) * eye_fix.CROP_SCALE)
        rbox = (eye["cx"] - rhalf, eye["cy"] - rhalf, eye["cx"] + rhalf, eye["cy"] + rhalf)
        region, _hair, fit = eye_fix.iris_region(original, eye, rbox)
        for key in ("add", "cut"):  # polygons (image coordinates) to take from Codex / keep from the original
            for poly in eye.get(key, []):
                img = Image.new("L", region.shape[::-1], 0)
                ImageDraw.Draw(img).polygon([(x - rbox[0], y - rbox[1]) for x, y in poly], fill=1)
                region = region | (np.asarray(img) > 0) if key == "add" else region & (np.asarray(img) == 0)
        full = np.zeros((original.height, original.width), np.float32)
        full[rbox[1]:rbox[3], rbox[0]:rbox[2]] = ndimage.gaussian_filter(region.astype(np.float32), 0.6) * region
        mask = Image.fromarray((full[box[1]:box[3], box[0]:box[2]] * 255).astype(np.uint8))
        base.paste(edited.resize((box[2] - box[0], box[3] - box[1]), Image.LANCZOS), box[:2], mask)
        print(f"eye {n} ({eye['kind']}): outline fit {fit['fit_share']:.2f}, iris area {fit['area']:.2f}, "
              f"pasted {int(region.sum())} px", flush=True)
        rows.append([original.crop(box).resize((360, 360), Image.LANCZOS), edited.resize((360, 360), Image.LANCZOS),
                     base.crop(box).resize((360, 360), Image.LANCZOS)])
    out.parent.mkdir(parents=True, exist_ok=True)
    base.save(out)
    sheet = Image.new("RGB", (3 * 370, len(rows) * 370), "white")
    for i, row in enumerate(rows):
        for j, im in enumerate(row):
            sheet.paste(im, (j * 370, i * 370))
    sheet.save(out.parent / (out.stem + "_eyecheck.png"))
    print(out)


if __name__ == "__main__":
    main()
