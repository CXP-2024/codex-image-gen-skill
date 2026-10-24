"""Hires-fix one region of a finished Krea 2 image: crop, upscale, low-denoise repaint, color-match, paste back.

For figures that are too small in a wide shot (face and hands collapse because they only get a few dozen pixels):
the box is cropped, upscaled `scale` times (Lanczos), repainted at `denoise` with the same style LoRAs and a prompt
that describes only what is in the box, color-matched back to the original crop (MKL), scaled down and pasted with a
feathered edge. Several denoise/seed combinations are rendered so the best one can be picked.

Job JSON:
{"image": "H:/.../in.png", "out_dir": "H:/.../fix", "box": [x0, y0, x1, y1], "scale": 3,
 "style": "kieed_cinema", "prompt": "...", "denoise": [0.4, 0.5], "seeds": [1, 2], "feather": 24,
 "mask": [[x, y], ...]}   # optional polygon (image coordinates) limiting the pasted area; default: the whole box
Writes <stem>_d<denoise>_s<seed>.png (full image) and <stem>_redraw_sheet.png (original crop + candidates).
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy import ndimage

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import generate  # noqa: E402

SERVER = "http://127.0.0.1:8288"


def repaint(upload_name, job, prompt, denoise, seed):
    k = generate.BACKENDS["krea2"]
    style = generate.STYLES.get(job.get("style", "kieed_cinema"), {})
    loras = job.get("loras", style.get("loras", []))
    model = ["1", 0]
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": k["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": k["clip"], "type": "krea2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": k["vae"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": style.get("trigger", "") + prompt, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "10": {"class_type": "LoadImage", "inputs": {"image": upload_name}},
        "11": {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["3", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "region_redraw/tmp"}},
    }
    for i, (name, strength) in enumerate(loras):
        g[f"20{i}"] = {"class_type": "LoraLoaderModelOnly",
                       "inputs": {"model": model, "lora_name": name, "strength_model": strength}}
        model = [f"20{i}", 0]
    g["7"] = {"class_type": "KSampler",
              "inputs": {"model": model, "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["11", 0],
                         "seed": seed, "steps": job.get("steps", 12), "cfg": 1.0, "sampler_name": "euler",
                         "scheduler": "simple", "denoise": denoise}}
    pid = generate.request(f"{SERVER}/prompt", {"prompt": g, "client_id": uuid.uuid4().hex}, timeout=600)["prompt_id"]
    while True:
        try:
            entry = generate.request(f"{SERVER}/history/{pid}").get(pid)
        except (TimeoutError, urllib.error.URLError):
            time.sleep(5)
            continue
        if entry and entry.get("status", {}).get("completed"):
            img = [i for o in entry["outputs"].values() for i in o.get("images", [])][0]
            url = f"{SERVER}/view?filename={img['filename']}&subfolder={img.get('subfolder', '')}&type=output"
            with urllib.request.urlopen(url, timeout=120) as r:
                return Image.open(BytesIO(r.read())).convert("RGB")
        if entry and entry.get("status", {}).get("status_str") == "error":
            sys.exit("repaint failed: " + json.dumps(entry["status"].get("messages", []))[:2000])
        time.sleep(1.5)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", required=True)
    a = ap.parse_args()
    job = json.loads(Path(a.job).read_text(encoding="utf-8-sig"))
    original = Image.open(job["image"]).convert("RGB")
    x0, y0, x1, y1 = job["box"]
    crop = original.crop((x0, y0, x1, y1))
    s = job.get("scale", 3)
    w, h = (round(crop.width * s / 16) * 16, round(crop.height * s / 16) * 16)
    out_dir = Path(job["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(job["image"]).stem.replace("_00001_", "")
    up_path = out_dir / f"{stem}_region_up.png"
    crop.resize((w, h), Image.LANCZOS).save(up_path)
    upload = generate.upload_image(SERVER, up_path)

    # Paste mask: the box (or polygon) with a feathered edge that stays inside the box.
    f = job.get("feather", 24)
    m = Image.new("L", crop.size, 0)
    if job.get("mask"):
        ImageDraw.Draw(m).polygon([(x - x0, y - y0) for x, y in job["mask"]], fill=255)
    else:
        ImageDraw.Draw(m).rectangle((f, f, crop.width - f, crop.height - f), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(f / 2))

    ref = np.asarray(crop, np.float32) / 255
    tiles = [("original", crop)]
    for d in job.get("denoise", [0.45]):
        for seed in job.get("seeds", [1]):
            t = time.time()
            raw_path = out_dir / f"{stem}_d{d}_s{seed}_raw.png"
            if raw_path.exists() and not job.get("redo"):  # reuse the repaint, redo only matching/pasting
                res = Image.open(raw_path).convert("RGB")
            else:
                res = repaint(upload, job, job["prompt"], d, seed)
                res.save(raw_path)
            res = res.resize(crop.size, Image.LANCZOS)
            arr = np.asarray(res, np.float32) / 255
            arr = (arr + job.get("color_match", 1.0) * (generate.mkl_transfer(arr, ref) - arr)).clip(0, 1)
            if job.get("lowfreq"):
                # Keep the original's broad tones (sigma in original pixels) and take only the new fine detail, so the
                # repainted box does not show as a lighter or darker rectangle.
                sg = (job["lowfreq"], job["lowfreq"], 0)
                arr = (arr + ndimage.gaussian_filter(ref, sg) - ndimage.gaussian_filter(arr, sg)).clip(0, 1)
            res = Image.fromarray((arr * 255).round().astype(np.uint8))
            full = original.copy()
            full.paste(res, (x0, y0), m)
            name = f"{stem}_d{d}_s{seed}"
            full.save(out_dir / f"{name}.png")
            tiles.append((f"denoise {d}, seed {seed}", full.crop((x0, y0, x1, y1))))
            print(f"{name}: {time.time() - t:.0f}s", flush=True)
    tw = 520
    th = round(crop.height * tw / crop.width)
    cols = min(4, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + 8), rows * (th + 40)), "white")
    dr = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    for i, (label, im) in enumerate(tiles):
        x, y = (i % cols) * (tw + 8), (i // cols) * (th + 40)
        dr.text((x + 4, y + 6), label, fill="black", font=font)
        sheet.paste(im.resize((tw, th), Image.LANCZOS), (x, y + 36))
    sheet.save(out_dir / f"{stem}_redraw_sheet.png")
    print(out_dir / f"{stem}_redraw_sheet.png")


if __name__ == "__main__":
    main()
