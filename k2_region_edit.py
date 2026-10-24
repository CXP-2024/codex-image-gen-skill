"""Fix one region of a finished image with Krea 2 + General Edit V2 (comfyui-krea2edit nodes), keeping the style.

The square `box` is cropped and resized to 1024, edited from the instruction by Krea 2 Turbo with the General Edit V2
LoRA plus the image's own style LoRA (default kieed 0.5), using the crop itself as the in-context source
(Krea2EditModelPatch + Krea2EditGroundedEncode). The result is color-matched to the original crop (MKL), scaled back
and pasted only inside `mask` with a feathered edge. Several ref_boost / seed combinations are rendered for picking:
higher ref_boost keeps more of the source, lower lets the edit change more.

Job JSON:
{"image": "H:/.../in.png", "out_dir": "H:/.../out", "box": [x0, y0, x1, y1], "prompt": "Fix the hand ...",
 "mask": [[x, y], ...], "feather": 6, "ref_boost": [2, 4], "seeds": [1, 2],
 "loras": [["krea2_general_edit_v2_r128.safetensors", 1.0], ["kieed_v1_epoch20.safetensors", 0.5]]}
Writes <stem>_rb<boost>_s<seed>.png (full image) and <stem>_k2edit_sheet.png.
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

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import generate  # noqa: E402

SERVER = "http://127.0.0.1:8288"
LORAS = [["krea2_general_edit_v2_r128.safetensors", 1.0], ["kieed_v1_epoch20.safetensors", 0.5]]


def graph(upload, prompt, seed, ref_boost, loras, grounding):
    k = generate.BACKENDS["krea2"]
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": k["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": k["clip"], "type": "krea2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": k["vae"]}},
        "10": {"class_type": "LoadImage", "inputs": {"image": upload}},
        "12": {"class_type": "EmptySD3LatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "13": {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["3", 0]}},
        "16": {"class_type": "Krea2EditGroundedEncode",
               "inputs": {"clip": ["2", 0], "prompt": prompt, "image": ["10", 0], "grounding_px": grounding}},
        "17": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["16", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "k2_region_edit/tmp"}},
    }
    model = ["1", 0]
    for i, (name, strength) in enumerate(loras):
        g[f"20{i}"] = {"class_type": "LoraLoaderModelOnly",
                       "inputs": {"model": model, "lora_name": name, "strength_model": strength}}
        model = [f"20{i}", 0]
    g["15"] = {"class_type": "Krea2EditModelPatch",
               "inputs": {"model": model, "source_latent": ["13", 0], "ref_boost": ref_boost, "fit_mode": "fit",
                          "vae": ["3", 0], "source_image": ["10", 0], "target_latent": ["12", 0],
                          "ref_position": "aligned (trained)"}}
    g["7"] = {"class_type": "KSampler",
              "inputs": {"model": ["15", 0], "positive": ["16", 0], "negative": ["17", 0], "latent_image": ["12", 0],
                         "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
                         "denoise": 1.0}}
    return g


def run(g):
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
            sys.exit("k2 edit failed: " + json.dumps(entry["status"].get("messages", []))[:2000])
        time.sleep(1.5)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--job", required=True)
    a = ap.parse_args()
    job = json.loads(Path(a.job).read_text(encoding="utf-8-sig"))
    original = Image.open(job["image"]).convert("RGB")
    x0, y0, x1, y1 = job["box"]
    crop = original.crop((x0, y0, x1, y1))
    out_dir = Path(job["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = job.get("name", Path(job["image"]).stem.replace("_00001_", ""))
    up = out_dir / f"{stem}_crop1024.png"
    crop.resize((1024, 1024), Image.LANCZOS).save(up)
    upload = generate.upload_image(SERVER, up)

    m = Image.new("L", crop.size, 0)
    ImageDraw.Draw(m).polygon([(x - x0, y - y0) for x, y in job["mask"]], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(job.get("feather", 6)))
    ref = np.asarray(crop, np.float32) / 255
    tiles = [("original", crop)]
    for rb in job.get("ref_boost", [2.0]):
        for seed in job.get("seeds", [1]):
            t = time.time()
            raw_path = out_dir / f"{stem}_rb{rb}_s{seed}_raw.png"
            if raw_path.exists():
                res = Image.open(raw_path).convert("RGB")
            else:
                res = run(graph(upload, job["prompt"], seed, rb, job.get("loras", LORAS), job.get("grounding_px", 768)))
                res.save(raw_path)
            arr = np.asarray(res.resize(crop.size, Image.LANCZOS), np.float32) / 255
            arr = (arr + job.get("color_match", 1.0) * (generate.mkl_transfer(arr, ref) - arr)).clip(0, 1)
            full = original.copy()
            full.paste(Image.fromarray((arr * 255).round().astype(np.uint8)), (x0, y0), m)
            name = f"{stem}_rb{rb}_s{seed}"
            full.save(out_dir / f"{name}.png")
            tiles.append((f"ref_boost {rb}, seed {seed}", full.crop((x0, y0, x1, y1))))
            print(f"{name}: {time.time() - t:.0f}s", flush=True)
    tw = 480
    cols = min(3, len(tiles))
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + 8), rows * (tw + 40)), "white")
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("arial.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    for i, (label, im) in enumerate(tiles):
        x, y = (i % cols) * (tw + 8), (i // cols) * (tw + 40)
        d.text((x + 4, y + 6), label, fill="black", font=font)
        sheet.paste(im.resize((tw, tw), Image.LANCZOS), (x, y + 36))
    sheet.save(out_dir / f"{stem}_k2edit_sheet.png")
    print(out_dir / f"{stem}_k2edit_sheet.png")


if __name__ == "__main__":
    main()
