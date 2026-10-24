"""Render a prompt through the local ComfyUI with one of the image-gen backends (core nodes only)."""

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

COMMON = {"seed": None, "batch": 1, "prefix": "image-gen/test"}

BACKENDS = {
    "anima": {
        "negative": "worst quality, low quality, lowres, bad anatomy, bad hands, "
                    "extra fingers, missing fingers, watermark, logo, signature, nsfw",
        "width": 832, "height": 1216, "steps": 30, "cfg": 4.5,
        "sampler": "euler", "scheduler": "sgm_uniform",
        "unet": "Anima-2.9B-preview-v1.safetensors",
        "clip": "qwen_3_06b_base.safetensors", "clip_type": "stable_diffusion",
        "vae": "qwen_image_vae.safetensors", "latent": "EmptyLatentImage",
        "loras": [],
    },
    "moss": {
        "negative": "nsfw, worst quality, low quality, bad anatomy, bad hands, "
                    "watermark, jpeg artifact, signature, text",
        "width": 896, "height": 1344, "steps": 50, "cfg": 3.5,
        "sampler": "euler", "scheduler": "simple",
        "unet": "moss_image_sft_int8_convrot.safetensors",
        "clip": "qwen3.5_9b_int8_convrot.safetensors", "clip_type": "moss_image",
        "vae": "flux2-vae.safetensors", "latent": "EmptyFlux2LatentImage",
        "slg": 0.0,
    },
    "krea2": {
        # Turbo is distilled: 8 steps, CFG 1, no real negative prompt (zeroed conditioning).
        "negative": "",
        "width": 1024, "height": 1536, "steps": 8, "cfg": 1.0,
        "sampler": "euler", "scheduler": "simple",
        "unet": "krea2_turbo_int8_convrot.safetensors",
        "clip": "qwen3vl_4b_fp8_scaled.safetensors", "clip_type": "krea2",
        "vae": "qwen_image_vae.safetensors", "latent": "EmptyLatentImage",
        "style_images": [], "style_strength": 1.0, "loras": [],
    },
}


# Named looks the user picked (2026-10-21). A job's "style" sets these and prepends the trigger to the prompt;
# fields written explicitly in the job still win.
STYLES = {
    "natarapisu": {"backend": "anima", "unet": "anima-base-v1.0.safetensors",
                   "loras": [["na_tarapisu153_style_v1.safetensors", 1.0]], "trigger": "@na tarapisu153, ",
                   "steps": 32, "hires": 1.5, "hires_denoise": 0.45, "hires_steps": 20},
    # Default since 2026-10-21: Krea 2 Turbo + kieed (Krea 2 epoch20) alone, community two-pass recipe.
    "kieed": {"backend": "krea2", "loras": [["kieed_v1_epoch20.safetensors", 1.0]], "trigger": "",
              "two_pass": True, "sampler": "euler", "scheduler": "simple", "width": 768, "height": 1152},
    # 2026-10-22: the community author's 5-LoRA cinematic recipe read from test13/test14.png (night alley, snowy
    # glasshouse): kieed at 0.65 plus mood/detail LoRAs, 8+8 two-pass, MKL color match 0.5, 21:9 at ~1 MP.
    # Melancholy forbids selling generated images.
    "kieed_cinema": {"backend": "krea2", "trigger": "zidiusArt, MSK, ",
                     "loras": [["Krea2_TextFusion_Refusal_Reduction.safetensors", 0.8],
                               ["Krea_2_zidiusArt_Melancholy_v2.safetensors", 0.3],
                               ["kieed_v1_epoch20.safetensors", 0.65],
                               ["z3zz4-k2-4_c1-st5000.safetensors", 0.45],
                               ["MSK_detailed_krea.safetensors", 0.4]],
                     "two_pass": True, "pass1_steps": 8, "pass2_steps": 8, "pass2_start": 4,
                     "pass2_seed_offset": 1, "color_match": 0.5,
                     "sampler": "euler", "scheduler": "simple", "width": 1568, "height": 672},
    # 2026-10-24: our own style LoRA trained on 80 works by ura (Pixiv 71432148), batch 4 x 900 steps.
    # Clean thin lines, soft pastel cel shading, round faces; affects the image even without the trigger.
    "ura": {"backend": "krea2", "loras": [["ura_style_k2_000000900.safetensors", 1.0]],
            "trigger": "uraStyle, an anime illustration by uraStyle. ",
            "two_pass": True, "sampler": "euler", "scheduler": "simple", "width": 832, "height": 1248},
    "kazutake": {"backend": "anima", "unet": "anima-base-v1.0.safetensors",
                 "loras": [["kazutake-hazano_v2_epoch28.safetensors", 1.0]], "trigger": "@4x0style, @kazutake hazano, ",
                 "steps": 32, "hires": 1.5, "hires_denoise": 0.45, "hires_steps": 20},
}
STYLE_NEGATIVE = ", signature, artist name, twitter username"


def build_krea2_graph(job):
    """Krea 2 Turbo, following Comfy-Org's official text-to-image and style-reference blueprints."""
    graph = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": job["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": job["clip"], "type": job["clip_type"], "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": job["vae"]}},
        "6": {"class_type": "EmptyLatentImage",
              "inputs": {"width": job["width"], "height": job["height"], "batch_size": job["batch"]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": job["prefix"]}},
    }
    model = ["1", 0]
    refs = job.get("style_uploaded", [])
    # "ref_mode": "character" feeds reference images (e.g. official character art) without the style-reference LoRA.
    use_style_lora = refs and job.get("ref_mode", "style") == "style"
    loras = ([["krea2_style_reference.safetensors", job["style_strength"]]] if use_style_lora else []) + job["loras"]
    for i, (name, strength) in enumerate(loras):
        node = f"20{i}"
        graph[node] = {"class_type": "LoraLoaderModelOnly",
                       "inputs": {"model": model, "lora_name": name, "strength_model": strength}}
        model = [node, 0]

    if not refs and job.get("two_pass"):
        # Community "Krea2高清二次采样" recipe: 7-step pass at base size, 2x bislerp latent upscale,
        # then a 10-step pass starting at step 4, all CFG 1 with zeroed negative conditioning.
        graph["4"] = {"class_type": "CLIPTextEncode", "inputs": {"text": job["prompt"], "clip": ["2", 0]}}
        graph["5"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}}
        common = {"model": model, "positive": ["4", 0], "negative": ["5", 0], "noise_seed": job["seed"],
                  "cfg": job["cfg"], "sampler_name": job["sampler"], "scheduler": job["scheduler"]}
        graph["7a"] = {"class_type": "KSamplerAdvanced",
                       "inputs": {**common, "latent_image": ["6", 0], "add_noise": "enable",
                                  "steps": job.get("pass1_steps", 7), "start_at_step": 0,
                                  "end_at_step": job.get("pass1_steps", 7),
                                  "return_with_leftover_noise": "enable"}}
        graph["7b"] = {"class_type": "LatentUpscaleBy",
                       "inputs": {"samples": ["7a", 0], "upscale_method": "bislerp",
                                  "scale_by": job.get("two_pass_scale", 2.0)}}
        graph["7"] = {"class_type": "KSamplerAdvanced",
                      "inputs": {**common, "latent_image": ["7b", 0], "add_noise": "enable",
                                 "noise_seed": job["seed"] + job.get("pass2_seed_offset", 0),
                                 "steps": job.get("pass2_steps", 10), "start_at_step": job.get("pass2_start", 4),
                                 "end_at_step": 10000, "return_with_leftover_noise": "disable"}}
        if job.get("color_match"):
            # The first-pass decode is the color reference for color_match() after download.
            graph["8a"] = {"class_type": "VAEDecode", "inputs": {"samples": ["7a", 0], "vae": ["3", 0]}}
            graph["9a"] = {"class_type": "SaveImage",
                           "inputs": {"images": ["8a", 0], "filename_prefix": job["prefix"] + "_firstpass"}}
        return graph

    if not refs:
        graph["4"] = {"class_type": "CLIPTextEncode", "inputs": {"text": job["prompt"], "clip": ["2", 0]}}
        graph["5"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}}
        graph["7"] = {"class_type": "KSampler",
                      "inputs": {"model": model, "positive": ["4", 0], "negative": ["5", 0],
                                 "latent_image": ["6", 0], "seed": job["seed"], "steps": job["steps"],
                                 "cfg": job["cfg"], "sampler_name": job["sampler"],
                                 "scheduler": job["scheduler"], "denoise": 1.0}}
        return graph

    encode = {"clip": ["2", 0], "vae": ["3", 0], "prompt": job["prompt"]}
    for i, name in enumerate(refs[:3], 1):
        graph[f"30{i}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        encode[f"image{i}"] = [f"30{i}", 0]
    graph["10"] = {"class_type": "ModelSamplingFlux",
                   "inputs": {"model": model, "max_shift": 1.15, "base_shift": 0.5,
                              "width": job["width"], "height": job["height"]}}
    graph["4"] = {"class_type": "TextEncodeQwenImageEditPlus", "inputs": encode}
    graph["11"] = {"class_type": "FluxKontextMultiReferenceLatentMethod",
                   "inputs": {"conditioning": ["4", 0], "reference_latents_method": "index_timestep_zero"}}
    graph["5"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["11", 0]}}
    graph["12"] = {"class_type": "CFGGuider",
                   "inputs": {"model": ["10", 0], "positive": ["11", 0], "negative": ["5", 0],
                              "cfg": job["cfg"]}}
    graph["13"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": job["seed"]}}
    graph["14"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": job["sampler"]}}
    graph["15"] = {"class_type": "BasicScheduler",
                   "inputs": {"model": ["10", 0], "scheduler": job["scheduler"],
                              "steps": job["steps"], "denoise": 1.0}}
    graph["7"] = {"class_type": "SamplerCustomAdvanced",
                  "inputs": {"noise": ["13", 0], "guider": ["12", 0], "sampler": ["14", 0],
                             "sigmas": ["15", 0], "latent_image": ["6", 0]}}
    return graph


def upload_image(server, path):
    """Upload a local image to ComfyUI's input folder and return the name LoadImage should use."""
    path = Path(path)
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + \
        f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{server}/upload/image", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=120) as reply:
        info = json.loads(reply.read().decode("utf-8"))
    return f"{info['subfolder']}/{info['name']}" if info.get("subfolder") else info["name"]


def build_graph(job):
    if job["clip_type"] == "krea2":
        return build_krea2_graph(job)
    model = ["1", 0]
    graph = {
        "1": {"class_type": "UNETLoader",
              "inputs": {"unet_name": job["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": job["clip"], "type": job["clip_type"], "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": job["vae"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": job["prompt"], "clip": ["2", 0]}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"text": job["negative"], "clip": ["2", 0]}},
        "6": {"class_type": job["latent"],
              "inputs": {"width": job["width"], "height": job["height"], "batch_size": job["batch"]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage",
              "inputs": {"images": ["8", 0], "filename_prefix": job["prefix"]}},
    }
    for i, (name, strength) in enumerate(job.get("loras", [])):
        node = f"20{i}"
        graph[node] = {"class_type": "LoraLoaderModelOnly",
                       "inputs": {"model": model, "lora_name": name, "strength_model": strength}}
        model = [node, 0]
    if job.get("slg"):
        # MOSS user guide: skip-layer guidance on single layer 22, scale ~3, active 0.01-1.0.
        graph["10"] = {"class_type": "SkipLayerGuidanceDiT",
                       "inputs": {"model": model, "double_layers": "", "single_layers": "22",
                                  "scale": job["slg"], "start_percent": 0.01, "end_percent": 1.0,
                                  "rescaling_scale": 0.0}}
        model = ["10", 0]
    graph["7"] = {"class_type": "KSampler",
                  "inputs": {"model": model, "positive": ["4", 0], "negative": ["5", 0],
                             "latent_image": ["6", 0], "seed": job["seed"], "steps": job["steps"],
                             "cfg": job["cfg"], "sampler_name": job["sampler"],
                             "scheduler": job["scheduler"], "denoise": 1.0}}
    if job.get("hires"):
        # Hires fix: decode, upscale in pixel space, re-encode, then repaint at low denoise.
        graph["17"] = {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}}
        graph["18"] = {"class_type": "ImageScaleBy",
                       "inputs": {"image": ["17", 0], "upscale_method": "lanczos", "scale_by": job["hires"]}}
        graph["19"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["18", 0], "vae": ["3", 0]}}
        graph["16"] = {"class_type": "KSampler",
                       "inputs": {"model": model, "positive": ["4", 0], "negative": ["5", 0],
                                  "latent_image": ["19", 0], "seed": job["seed"],
                                  "steps": job.get("hires_steps", job["steps"]), "cfg": job["cfg"],
                                  "sampler_name": job["sampler"], "scheduler": job["scheduler"],
                                  "denoise": job.get("hires_denoise", 0.45)}}
        graph["8"]["inputs"]["samples"] = ["16", 0]
    return graph


def mkl_transfer(src, ref):
    """Monge-Kantorovich linear color transfer (the 'mkl' method of color-matcher, as in KJNodes ColorMatchV2)."""
    import numpy as np
    z, r = src.reshape(-1, 3), ref.reshape(-1, 3)
    cz, cr = np.cov(z.T), np.cov(r.T)
    da2, ua = np.linalg.eigh(cz)
    da = np.diag(np.sqrt(da2.clip(1e-10)))
    dc2, uc = np.linalg.eigh(da @ ua.T @ cr @ ua @ da)
    dc = np.diag(np.sqrt(dc2.clip(1e-10)))
    da_inv = np.diag(1 / np.diag(da))
    t = ua @ da_inv @ uc @ dc @ uc.T @ da_inv @ ua.T
    return ((z - z.mean(0)) @ t + r.mean(0)).reshape(src.shape)


def color_match(target_path, ref_path, strength):
    """Pull the hi-res pass back toward the first pass's colors (two-pass sampling drifts); overwrites target.

    Keeps ComfyUI's PNG text chunks (the workflow "prompt") and records the post-step, since it is not in the graph.
    """
    import numpy as np
    from PIL import Image
    src = Image.open(target_path)
    tgt = np.asarray(src.convert("RGB"), np.float32) / 255
    ref = np.asarray(Image.open(ref_path).convert("RGB"), np.float32) / 255
    out = (tgt + strength * (mkl_transfer(tgt, ref) - tgt)).clip(0, 1)
    meta = png_text(src.info, {"postprocess": json.dumps(
        {"color_match": {"method": "mkl", "strength": strength, "reference": Path(ref_path).name}})})
    Image.fromarray((out * 255).round().astype(np.uint8)).save(target_path, pnginfo=meta)


def png_text(info, extra=None):
    """PngInfo with the existing text chunks of `info` (ComfyUI's prompt/workflow) plus `extra`."""
    from PIL.PngImagePlugin import PngInfo
    meta = PngInfo()
    for key, value in {**{k: v for k, v in info.items() if isinstance(v, str)}, **(extra or {})}.items():
        meta.add_text(key, value)
    return meta


def request(url, payload=None, timeout=30):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as reply:
        return json.loads(reply.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", help="UTF-8 JSON file with prompt/negative/width/... fields")
    parser.add_argument("--prompt", help="positive prompt (overrides the job file)")
    parser.add_argument("--backend", choices=sorted(BACKENDS),
                        help="overrides the job file's backend (default krea2)")
    parser.add_argument("--server", default="http://127.0.0.1:8288")
    parser.add_argument("--output-root", default=r"H:\ComfyUI-latest\output")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    loaded = json.loads(Path(args.job).read_text(encoding="utf-8-sig")) if args.job else {}
    style = STYLES.get(loaded.get("style", ""), {})
    if loaded.get("style") and not style:
        sys.exit(f"unknown style {loaded['style']!r}; choose from {sorted(STYLES)}")
    backend = args.backend or loaded.get("backend") or style.get("backend", "krea2")
    if backend not in BACKENDS:
        sys.exit(f"unknown backend {backend!r}; choose from {sorted(BACKENDS)}")
    job = {**COMMON, **BACKENDS[backend], **{k: v for k, v in style.items() if k != "trigger"}, **loaded}
    if style:
        job["negative"] = job["negative"] + STYLE_NEGATIVE
    if args.prompt:
        job["prompt"] = args.prompt
    if not job.get("prompt"):
        sys.exit("prompt is required (--prompt or a job file)")
    if style and style["trigger"] not in job["prompt"]:
        # Trigger goes after the quality/safety prefix if the prompt starts with one, else at the front.
        head, sep, rest = job["prompt"].partition(" safe, ")
        job["prompt"] = (head + sep + style["trigger"] + rest) if sep else style["trigger"] + job["prompt"]
    if job["seed"] is None:
        job["seed"] = random.randint(1, 2**32 - 1)

    try:
        job["style_uploaded"] = [upload_image(args.server, p) for p in job.get("style_images", [])]
        # Long timeout: ComfyUI can stall for minutes while it swaps a large model for the previous job.
        reply = request(f"{args.server}/prompt",
                        {"prompt": build_graph(job), "client_id": uuid.uuid4().hex}, timeout=600)
    except urllib.error.HTTPError as error:
        sys.exit(f"ComfyUI rejected the graph: {error.read().decode('utf-8', 'replace')}")
    except urllib.error.URLError as error:
        sys.exit(f"ComfyUI is not reachable at {args.server}: {error.reason}")
    prompt_id = reply["prompt_id"]

    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        try:
            entry = request(f"{args.server}/history/{prompt_id}").get(prompt_id)
        except (TimeoutError, urllib.error.URLError):  # ComfyUI stalls briefly while swapping large models
            time.sleep(5)
            continue
        if entry:
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                sys.exit("generation failed: " + json.dumps(status.get("messages", []), ensure_ascii=False))
            if status.get("completed"):
                outputs = {nid: [str(Path(args.output_root, img.get("subfolder", ""), img["filename"]))
                                 for img in out.get("images", [])] for nid, out in entry["outputs"].items()}
                paths = outputs.get("9", [])
                if job.get("color_match") and outputs.get("9a"):
                    for final, first in zip(paths, outputs["9a"]):
                        color_match(final, first, job["color_match"])
                print(json.dumps({"backend": backend, "prompt_id": prompt_id, "seed": job["seed"],
                                  "images": paths}, ensure_ascii=False, indent=2))
                return
        time.sleep(1.5)
    sys.exit(f"timed out waiting for {prompt_id}")


if __name__ == "__main__":
    main()
