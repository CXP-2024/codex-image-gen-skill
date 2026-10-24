"""Build the LoRA gallery: one sample per style LoRA with the same prompt and seed, plus LORA_GALLERY.md.

Usage:  python build_gallery.py [--redo ID ...]
Reads loras.json next to this file. For every krea2/anima entry without samples/<id>.jpg it renders the sample
through generate.py (ComfyUI must be running on :8288), then rebuilds the contact sheets and LORA_GALLERY.md.
Run it after adding, removing or re-testing a LoRA (edit loras.json first).
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
SAMPLES = HERE / "samples"
OUTPUT = Path(r"H:\ComfyUI-latest\output")
GROUPS = {"krea2": "Krea 2 Turbo（K2）画风 LoRA", "anima": "Anima 画风 LoRA"}


def job_for(entry, reg):
    if entry["group"] == "krea2":
        prompt = entry["trigger"] + reg["prompt_krea2"] + entry.get("suffix", "")
        return {"backend": "krea2", "prompt": prompt, "seed": reg["seed"], "sampler": "euler", "scheduler": "simple",
                "prefix": f"krea2/lora_gallery/{entry['id']}", "loras": entry["loras"], "two_pass": True,
                "width": 832, "height": 1248}
    return {"backend": "anima", "unet": "anima-base-v1.0.safetensors", "prompt": entry["trigger"] + reg["prompt_anima"],
            "seed": reg["seed"], "prefix": f"anima/lora_gallery/{entry['id']}", "loras": entry["loras"], "steps": 32,
            "hires": 1.5, "hires_denoise": 0.45, "hires_steps": 20, "width": 832, "height": 1216}


def newest_output(entry):
    hits = sorted((OUTPUT / entry["group"] / "lora_gallery").glob(f"{entry['id']}_*.png"), key=lambda p: p.stat().st_mtime)
    return hits[-1] if hits else None


def ensure_sample(entry, reg, redo):
    out = SAMPLES / f"{entry['id']}.jpg"
    if out.exists() and not redo:
        return out
    src = None if redo else newest_output(entry)
    if src is None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(job_for(entry, reg), f, ensure_ascii=False)
        print("render", entry["id"], flush=True)
        subprocess.run([sys.executable, str(SKILL / "generate.py"), "--job", f.name], check=True, capture_output=True)
        src = newest_output(entry)
    im = Image.open(src).convert("RGB")
    im.thumbnail((1024, 1024))
    im.save(out, quality=90)
    return out


def sheet(entries, path):
    cell_w, cell_h, cols = 360, 560, 5
    font = ImageFont.truetype("msyh.ttc", 20)
    rows = (len(entries) + cols - 1) // cols
    s = Image.new("RGB", (cols * cell_w, rows * (cell_h + 58)), "white")
    d = ImageDraw.Draw(s)
    for k, e in enumerate(entries):
        im = Image.open(SAMPLES / f"{e['id']}.jpg")
        im.thumbnail((cell_w - 8, cell_h - 8))
        x, y = (k % cols) * cell_w, (k // cols) * (cell_h + 58)
        s.paste(im, (x + (cell_w - im.width) // 2, y + 58))
        name = e["name"]
        cut = next((i for i in range(len(name), 0, -1) if d.textlength(name[:i], font=font) <= cell_w - 12), len(name))
        d.text((x + 6, y + 4), name[:cut], fill="black", font=font)
        d.text((x + 6, y + 28), name[cut:], fill="black", font=font)
    s.save(path, quality=86)


def cell(text):
    return (text or "").replace("|", "／").replace("\n", " ")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--redo", nargs="*", default=[], help="ids to render again")
    a = ap.parse_args()
    reg = json.loads((HERE / "loras.json").read_text(encoding="utf-8"))
    SAMPLES.mkdir(exist_ok=True)
    lines = ["# 本地 LoRA 效果图鉴", "",
             "自动生成，不要手改：改 `loras.json` 后运行 `python build_gallery.py`。",
             f"同一组内的样图用同一段芙宁娜提示词、同一 seed（{reg['seed']}）生成，只换 LoRA 和触发词；"
             "K2 为两段采样 832×1248，Anima 为 32 步 + 1.5 倍高清修复。", "",
             "「可卖图」指 Civitai 页面上作者是否允许出售生成的图片；不确定的一律只自用。", ""]
    for group, title in GROUPS.items():
        entries = [e for e in reg["loras"] if e["group"] == group]
        if not entries:
            continue
        for e in entries:
            ensure_sample(e, reg, e["id"] in a.redo)
        sheet(entries, HERE / f"sheet_{group}.jpg")
        lines += [f"## {title}", "", f"![{title}](sheet_{group}.jpg)", "",
                  "| 样图 | 名称 | 文件（强度） | 触发词 | 预设 | 用途 / 效果 | 许可 | 来源 |",
                  "|---|---|---|---|---|---|---|---|"]
        for e in entries:
            files = "<br>".join(f"`{n}` ({s})" for n, s in e["loras"]) or "—"
            trig = f"`{e['trigger'].strip()}`" if e["trigger"].strip() else ("`" + e["suffix"].strip() + "`（末尾）" if e.get("suffix") else "无")
            src = e.get("source", "")
            src = f"[链接]({src})" if src.startswith("http") else cell(src)
            lines.append(f"| [看图](samples/{e['id']}.jpg) | {cell(e['name'])} | {files} | {trig} | "
                         f"{('`style: ' + e['preset'] + '`') if e.get('preset') else ''} | {cell(e.get('use'))} | "
                         f"{cell(e.get('license', ''))} | {src} |")
        lines.append("")
    if reg.get("_removed"):
        lines += ["## 已移除", "", reg["_removed"], ""]
    util = [e for e in reg["loras"] if e["group"] == "utility"]
    lines += ["## 功能类 LoRA（不改画风，不出样图）", "", "| 名称 | 文件（常用强度） | 用途 | 来源 |", "|---|---|---|---|"]
    for e in util:
        files = "<br>".join(f"`{n}` ({s})" for n, s in e["loras"])
        src = e.get("source", "")
        src = f"[链接]({src})" if src.startswith("http") else cell(src)
        lines.append(f"| {cell(e['name'])} | {files} | {cell(e.get('use'))} | {src} |")
    (HERE / "LORA_GALLERY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote", HERE / "LORA_GALLERY.md")


if __name__ == "__main__":
    main()
