"""Repaint individual eyes on a finished Krea 2 image, one eye per pass, and blend them back.

Each eye is cropped around its center, upscaled, repainted inside an elliptical mask with a prompt that describes
only that eye (so the model cannot swap left/right attributes), then pasted back with a feathered mask.

Job JSON:
{"image": "H:\\...\\in.png", "out": "H:\\...\\out.png", "seed": 1,
 "eyes": [{"cx": 595, "cy": 580, "r": 50, "kind": "light"}, {"cx": 785, "cy": 620, "r": 40, "kind": "dark"}],
 "loras": [["kieed_v1_epoch20.safetensors", 0.6]], "denoise": 0.6}
"kind" picks a preset eye description from EYE_PROMPTS, or pass "prompt" per eye instead.
Light hair strands that reach into the eye from outside are kept in front automatically ("keep_hair", default
true; turn it off when a tinted lens covers the eye, and use "restore" for the lens reflection instead).
"""

import argparse
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from scipy import ndimage
from scipy.optimize import least_squares
from scipy.spatial import ConvexHull

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate  # noqa: E402

EYE_PROMPTS = {
    # Furina's official design (character card art): the two eyes use reversed colors. "light" is her RIGHT eye,
    # "dark" her LEFT eye; when she faces the viewer the light eye is on the viewer's left.
    "light": ("Extreme close-up of a single anime eye in a delicate hand-painted illustration. The iris is pale "
              "luminous sky blue and cyan with fine radial streaks and a thin dark navy outer ring. The pupil is a "
              "slender dark violet-blue water droplet pointing straight up, set high in the iris and reaching up to "
              "its top edge. A soft white highlight sits at the bottom of the iris. Clean anime linework, cel shading."),
    "dark": ("Extreme close-up of a single anime eye in a delicate hand-painted illustration. The iris is deep "
             "violet-blue indigo with a thin pinkish-violet rim along its lower edge and a dark navy outer ring. The "
             "pupil is a slender light cyan water droplet pointing straight up, set high in the iris and reaching up "
             "to its top edge, glowing against the dark iris, with a few tiny white streaks. Clean anime linework, "
             "cel shading."),
}
# Color sketch drawn under the repaint so the shape and colors are exact; the model only re-renders it in style.
GUIDE_COLORS = {
    "light": {"inner": (200, 234, 250), "outer": (105, 165, 232), "ring": (30, 50, 140), "drop": (72, 70, 190),
              "drop_edge": (38, 36, 130), "streak": (238, 248, 255), "rim": None},
    "dark": {"inner": (100, 92, 214), "outer": (52, 44, 158), "ring": (28, 24, 100), "drop": (170, 236, 250),
             "drop_edge": (105, 196, 232), "streak": (240, 245, 255), "rim": (205, 145, 232)},
}


def draw_guide(crop, kind, rx, ry, angle=0.0, center=None, region=None, drop_shift=0.0):
    """Paint Furina's iris design onto the crop: gradient iris, ring, slim upward drop pupil, details.

    center: iris center in crop pixels (default: crop center). region: bool array (crop size) of the visible iris;
    when given, the design is only painted inside it and the dark ring follows the region's own edge, so the guide
    lines up with the original outline and eyelid exactly.
    """
    c = GUIDE_COLORS[kind]
    s = 3  # supersample for clean edges
    size = crop.size[0] * s
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = (size / 2, size / 2) if center is None else (center[0] * s, center[1] * s)
    RX, RY = rx * s, ry * s
    for i in range(40, 0, -1):  # radial gradient from outer to inner color
        t = i / 40
        col = tuple(int(c["inner"][k] + (c["outer"][k] - c["inner"][k]) * t ** 1.4) for k in range(3))
        d.ellipse((cx - RX * t, cy - RY * t, cx + RX * t, cy + RY * t), fill=col + (255,))
    if c["rim"]:
        d.arc((cx - RX * 0.93, cy - RY * 0.93, cx + RX * 0.93, cy + RY * 0.93), 20, 160, fill=c["rim"] + (255,),
              width=int(RX * 0.09))
    if kind == "light":
        for a in np.linspace(0, 2 * np.pi, 22, endpoint=False):
            r0, r1 = 0.45, 0.85
            d.line((cx + RX * r0 * np.cos(a), cy + RY * r0 * np.sin(a), cx + RX * r1 * np.cos(a),
                    cy + RY * r1 * np.sin(a)), fill=c["streak"] + (110,), width=max(2, int(RX * 0.025)))
    if region is None:
        d.ellipse((cx - RX, cy - RY, cx + RX, cy + RY), outline=c["ring"] + (255,), width=int(RX * 0.08))
    # Slender teardrop: tip near the top edge, round bottom just above center. drop_shift (in RY) moves it down
    # when the eyelid hides the top of the iris, so the tip stays visible.
    w, body_y, tip_y = RX * 0.27, cy - RY * (0.12 - drop_shift), cy - RY * (0.86 - drop_shift)
    dist = body_y - tip_y
    phi = np.arccos(min(1.0, w / dist))
    angles = np.linspace(-np.pi / 2 + phi, 3 * np.pi / 2 - phi, 60)
    pts = [(cx, tip_y)] + [(cx + w * np.cos(a), body_y + w * np.sin(a)) for a in angles]
    d.polygon(pts, fill=c["drop"] + (255,), outline=c["drop_edge"] + (255,), width=int(RX * 0.04))
    hl = RX * 0.13
    if kind == "light":
        d.ellipse((cx - hl * 1.6, cy + RY * 0.55, cx + hl * 0.4, cy + RY * 0.55 + hl), fill=(255, 255, 255, 235))
    else:
        for dx, dy in ((0.35, -0.1), (-0.4, 0.25), (0.25, 0.45)):
            d.line((cx + RX * dx, cy + RY * dy, cx + RX * (dx + 0.08), cy + RY * (dy - 0.12)),
                   fill=c["streak"] + (220,), width=int(RX * 0.035))
    layer = layer.rotate(angle, resample=Image.BICUBIC, center=(cx, cy)).resize(crop.size, Image.LANCZOS)
    if region is not None:
        la = np.asarray(layer).astype(np.float32)
        la[..., 3] *= region
        ring = region & (ndimage.distance_transform_edt(region) < max(1.5, rx * 0.09))
        la[ring] = list(c["ring"]) + [255]
        layer = Image.fromarray(la.astype(np.uint8))
    out = crop.convert("RGBA")
    out.alpha_composite(layer)
    return out.convert("RGB")


LINE_MAX = 95       # max(R, G, B) below this counts as line art: iris outline, eyelids, lashes, old pupil


def fit_outline(dark, sx, sy, r, ry, t):
    """Fit an ellipse to the INNER edge of the drawn iris outline.

    Casts rays outward from inside the iris (0.68x the measured ellipse, beyond the pupil) over the sides and the
    bottom; the first dark pixel on each ray is the inner edge of the outline. The top is skipped: there the first
    dark pixel is the upper lid, not the iris. Points on the lower lid or a hair line are rejected by the robust fit.
    Returns (cx, cy, A, B, phi, inlier share) in crop pixels, or None when too few rays hit an outline.
    """
    pts = []
    h, w = dark.shape
    for q in np.radians(np.arange(-25, 206, 3)):  # face frame, y down: -25..205 deg = sides and bottom
        dx, dy = np.cos(q), np.sin(q)
        rr = 1 / np.sqrt((dx / r) ** 2 + (dy / ry) ** 2)
        ix, iy = dx * np.cos(t) + dy * np.sin(t), -dx * np.sin(t) + dy * np.cos(t)
        for s in np.arange(0.68 * rr, 1.35 * rr, 0.5):
            x, y = int(round(sx + ix * s)), int(round(sy + iy * s))
            if 0 <= x < w and 0 <= y < h and dark[y, x]:
                pts.append((sx + ix * (s - 0.5), sy + iy * (s - 0.5)))
                break
    if len(pts) < 25:
        return None
    pts = np.array(pts)
    phi = -t  # the iris axes follow the head tilt

    def residual(p, P):
        ecx, ecy, A, k = p  # k = height / width: anime irises are round or taller than wide
        u = (P[:, 0] - ecx) * np.cos(phi) + (P[:, 1] - ecy) * np.sin(phi)
        v = -(P[:, 0] - ecx) * np.sin(phi) + (P[:, 1] - ecy) * np.cos(phi)
        return (np.sqrt((u / A) ** 2 + (v / (k * A)) ** 2) - 1) * A

    p0 = [sx, sy, 0.92 * r, float(np.clip(ry / r, 1.0, 1.35))]
    lb = [sx - 0.4 * r, sy - 0.4 * ry, 0.6 * r, 1.0]
    ub = [sx + 0.4 * r, sy + 0.4 * ry, 1.4 * r, 1.4]
    p = least_squares(residual, p0, bounds=(lb, ub), loss="soft_l1", f_scale=1.5, args=(pts,)).x
    tol = max(1.5, 0.05 * min(r, ry))
    for _ in range(2):  # trimmed refits on the points that agree with the outline
        inl = np.abs(residual(p, pts)) < tol
        if inl.sum() < 15:
            return None
        p = least_squares(residual, p, bounds=(lb, ub), args=(pts[inl],)).x
    inl = np.abs(residual(p, pts)) < tol
    ecx, ecy, A, k = p
    return ecx, ecy, A, k * A, phi, inl.mean()


def iris_region(base, eye, box):
    """Visible iris of one eye in the ORIGINAL image as a bool mask over `box`, plus hair over it and fit info.

    1. An ellipse is fitted to the inner edge of the drawn iris outline (fit_outline), so the area matches the old
       iris exactly: nothing of the old rim stays outside it and the new iris never reaches past it.
    2. Inside that ellipse, the area reachable from seeds in the lower iris without crossing line art is the
       visible iris: the upper lid and lashes stop it, skin above the lid is not reached. Holes (old pupil,
       highlights) are filled and a convex hull covers a pupil that touches the lid.
    3. Thin dark lines that come in from outside near the upper edge (lashes dipping into the iris) stay out.
    4. Light, unsaturated pixels that continue well outside the ellipse are translucent hair over the eye: they are
       repainted too (the iris goes on under them) but re-tinted with the hair color afterwards (see main()).
    """
    cx, cy, r = eye["cx"], eye["cy"], eye["r"]
    ry = eye.get("ry", r * 1.1)
    t = np.radians(eye.get("angle", 0.0))
    a = np.asarray(base.crop(box), np.int16)
    yy, xx = np.mgrid[0:a.shape[0], 0:a.shape[1]]
    sx, sy = cx - box[0], cy - box[1]
    dark = a.max(axis=2) < eye.get("line_max", LINE_MAX)
    fitted = None if eye.get("fit") is False else fit_outline(dark, sx, sy, r, ry, t)
    if fitted and fitted[5] >= eye.get("min_inliers", 0.4):
        ecx, ecy, A, B, phi, share = fitted
    else:
        ecx, ecy, A, B, phi, share = sx, sy, r, ry, -t, 0.0
    u = (xx - ecx) * np.cos(phi) + (yy - ecy) * np.sin(phi)
    v = -(xx - ecx) * np.sin(phi) + (yy - ecy) * np.cos(phi)
    e = np.sqrt((u / A) ** 2 + (v / B) ** 2)
    inside = e <= 1 + eye.get("grow_px", 0.7) / min(A, B)
    # The fit only sees the sides and bottom, so the hidden top may be taller than fitted: allow up to `top_extra`
    # more height above the center there, but only over iris-colored pixels (not skin, eye white or hair, where the
    # top of the iris is only faintly drawn through the bangs); the upper lid line stops the growth anyway.
    e_top = np.sqrt((u / A) ** 2 + (v / (B * eye.get("top_extra", 1.2))) ** 2)
    skin = (a[..., 0] > a[..., 2] + 20) & ~dark
    pale = (a.min(axis=2) > eye.get("hair_min", 178)) & (a.max(axis=2) - a.min(axis=2) < eye.get("hair_sat", 34))
    pl, _ = ndimage.label(pale)  # pale areas reaching outside are hair or eye white; isolated ones are highlights
    out_ids = np.unique(pl[pale & (e_top > 1.05)])
    pale_out = np.isin(pl, out_ids[out_ids > 0])
    inside |= (v < 0) & (e_top <= 1) & ~skin & ~pale_out
    # What stops the growth: lid and lash lines (brown/black) and thin dark lines that run far outside the iris
    # (hair strand outlines over the eye). Navy dark areas inside are iris: the shading under the lid, the old pupil
    # and its outline. They are grown over and repainted.
    neutral = (a[..., 2] - a[..., 0]) < 15
    thin = dark & ~ndimage.binary_opening(dark, iterations=max(1, round(0.05 * min(A, B))))
    tl, _ = ndimage.label(thin)
    far = np.unique(tl[thin & (e > 1.35)])
    wall = (dark & neutral) | np.isin(tl, far[far > 0])
    free, _ = ndimage.label(inside & ~wall)
    # Seeds on a ring in the lower half (usually visible, and outside the pupil, whose closed outline would trap a
    # center seed). A patch must be bluish on average so skin above the lid, inside the ellipse, is never taken.
    seeds = [[ecx + 0.65 * A * np.cos(q - t), ecy + 0.65 * B * np.sin(q - t)]
             for q in np.radians(np.arange(20, 161, 20))]
    seeds += [[px - box[0], py - box[1]] for px, py in eye.get("seeds", [])]
    grown = np.zeros(e.shape, bool)
    for px, py in seeds:
        px, py = int(round(px)), int(round(py))
        if 0 <= py < e.shape[0] and 0 <= px < e.shape[1] and free[py, px]:
            patch = free == free[py, px]
            if (a[patch][:, 2] - a[patch][:, 0]).mean() > -5:
                grown |= patch
    if not grown.any():
        raise SystemExit(f"eye at ({cx}, {cy}): no iris area found, check cx/cy/r")
    grown = ndimage.binary_fill_holes(grown)
    pts = np.argwhere(grown)[:, ::-1].astype(np.float64)
    hull_img = Image.new("L", (a.shape[1], a.shape[0]), 0)
    ImageDraw.Draw(hull_img).polygon([tuple(p) for p in pts[ConvexHull(pts).vertices]], fill=1, outline=1)
    region = (np.asarray(hull_img) > 0) & inside
    # Lashes and hair lines that the hull bridged over stay in front: thin wall lines in the upper part, near the
    # region's edge, outside the old pupil (its outline is often black too and touches the lid; it is repainted).
    fy = (xx - ecx) * np.sin(t) + (yy - ecy) * np.cos(t)
    dl, _ = ndimage.label(dark & (e < 0.95))
    pids = np.unique(dl[dark & (e < 0.55)])
    pupil = ndimage.binary_dilation(ndimage.binary_fill_holes(np.isin(dl, pids[pids > 0])), iterations=2)
    edge_band = ndimage.distance_transform_edt(region) < 0.2 * min(A, B)
    lashes = wall & thin & region & (fy < 0) & edge_band & ~pupil
    if min(A, B) >= 14:  # on tiny eyes lashes and pupil are a few pixels each and cannot be told apart
        region = ndimage.binary_fill_holes(region & ~lashes)
    # Translucent bangs over the iris: much lighter than the clean lower iris and connected to the region's upper
    # edge (bangs come from above). Reliable on the dark eye; on a pale iris hair and iris have the same lightness,
    # so there it only triggers with "hair": "auto". Hand-drawn "hair" polygons (image coordinates) also work.
    lum = a @ np.array([0.299, 0.587, 0.114])
    clean = region & (fy > 0.3 * B) & ~dark & (a.min(axis=2) < 235)
    hair = np.zeros_like(region)
    mode = eye.get("hair", "dark" if eye.get("kind") == "dark" else "off")
    if mode in ("auto", "dark") and clean.sum() > 30:
        cand = region & (lum > np.median(lum[clean]) + eye.get("hair_delta", 45))
        top_edge = region & ~ndimage.binary_erosion(region) & (fy < 0)
        cl, _ = ndimage.label(cand)
        ids = np.unique(cl[cand & ndimage.binary_dilation(top_edge, iterations=2)])
        hair = ndimage.binary_opening(np.isin(cl, ids[ids > 0]), iterations=1)
        if hair.sum() < 0.03 * region.sum():
            hair = np.zeros_like(region)
    hair_zone = np.zeros_like(region)
    polys = [[(x - box[0], y - box[1]) for x, y in poly] for poly in eye.get("hair_polys", [])]
    if eye.get("hair_line"):
        # Edge of the bangs drawn as a polyline across the eye; the hair is on `hair_side` of it.
        pl = [(x - box[0], y - box[1]) for x, y in eye["hair_line"]]
        W, H = region.shape[1] - 1, region.shape[0] - 1
        close = {"above": [(pl[-1][0], 0), (pl[0][0], 0)], "below": [(pl[-1][0], H), (pl[0][0], H)],
                 "left": [(0, pl[-1][1]), (0, pl[0][1])], "right": [(W, pl[-1][1]), (W, pl[0][1])]}
        polys.append(pl + close[eye.get("hair_side", "above")])
    for poly in polys:
        img = Image.new("L", region.shape[::-1], 0)
        ImageDraw.Draw(img).polygon(poly, fill=1)
        hair_zone |= np.asarray(img) > 0
    hair |= hair_zone & region
    fx = (xx - ecx) * np.cos(t) - (yy - ecy) * np.sin(t)
    fit = {"cx": ecx, "cy": ecy, "r": A, "ry": B, "fit_share": share, "scale": A / r,
           "area": region.sum() / (np.pi * A * B), "top": fy[region].min() / B if region.any() else 0.0,
           "width": (fx[region].max() - fx[region].min()) / (2 * A) if region.any() else 0.0,
           "hair": hair.sum() / max(1, region.sum())}
    if hair.any():
        # Hair color from the same strands just outside the iris; iris color under the hair from the nearest
        # hair-free iris pixels (smoothed), so the opacity can be solved per pixel (see hair_alpha).
        outside_hair = hair_zone & (e > 1.1) & (e < 1.8) & ~dark & ~skin
        src = outside_hair if outside_hair.sum() > 20 else hair
        fit["hair_color"] = np.median(a[src][lum[src] >= np.percentile(lum[src], 50)], axis=0)
        clear = region & ~hair & ~dark
        if clear.sum() < 20:
            clear = region & ~hair
        _, (iy, ix) = ndimage.distance_transform_edt(~clear, return_indices=True)
        under = a[iy, ix].astype(np.float32)
        fit["iris_under"] = np.stack([ndimage.gaussian_filter(under[..., c], 0.08 * min(A, B)) for c in range(3)], -1)
    return region, hair, fit


def hair_alpha(orig, hair, hair_color, iris_under):
    """Per-pixel opacity of translucent hair over the iris, assuming orig = (1 - a) * iris + a * hair color."""
    d = hair_color[None, None, :] - iris_under
    a = ((orig - iris_under) * d).sum(-1) / np.maximum(1.0, (d * d).sum(-1))
    return ndimage.gaussian_filter(np.where(hair, a.clip(0, 0.92), 0).astype(np.float32), 0.8) * hair


def check_image(crop, region, guide, result, path, hair=None):
    """Zoomed panels for review: original with the repaint boundary (magenta) and translucent hair (cyan),
    the guide, the result with the boundary, and the plain result."""
    edge = region & ~ndimage.binary_erosion(region)
    hedge = None if hair is None or not hair.any() else hair & ~ndimage.binary_erosion(hair)
    panels = []
    for i, img in enumerate((crop, guide, result, result)):
        if img is None:
            continue
        p = np.asarray(img.convert("RGB")).copy()
        if i < 3:
            p[edge] = (255, 0, 255)
            if hedge is not None and i == 0:
                p[hedge] = (0, 230, 255)
        panels.append(Image.fromarray(p).resize((384, 384), Image.NEAREST))
    sheet = Image.new("RGB", (len(panels) * 394 - 10, 384), "white")
    for i, p in enumerate(panels):
        sheet.paste(p, (i * 394, 0))
    sheet.save(path)


CROP_SCALE = 2.4    # crop half-size = r * CROP_SCALE
MASK_SCALE = 1.0    # repainted ellipse = iris radius; keep it off the eyelids or they smear
WORK = 768          # crops are repainted at this size


def repaint(server, crop, mask, prompt, job, tag):
    rgba = crop.convert("RGBA")
    rgba.putalpha(Image.eval(mask, lambda v: 255 - v))  # ComfyUI LoadImage mask = 1 - alpha
    tmp = Path(generate.__file__).parent / f"_eye_{tag}.png"
    rgba.save(tmp)
    name = generate.upload_image(server, tmp)
    tmp.unlink()
    model = ["1", 0]
    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": job["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": job["clip"], "type": "krea2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": job["vae"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "10": {"class_type": "LoadImage", "inputs": {"image": name}},
        "11": {"class_type": "VAEEncode", "inputs": {"pixels": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["11", 0], "mask": ["10", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "eye_fix/tmp"}},
    }
    for i, (lname, strength) in enumerate(job["loras"]):
        graph[f"20{i}"] = {"class_type": "LoraLoaderModelOnly",
                           "inputs": {"model": model, "lora_name": lname, "strength_model": strength}}
        model = [f"20{i}", 0]
    graph["7"] = {"class_type": "KSampler",
                  "inputs": {"model": model, "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["12", 0],
                             "seed": job["seed"], "steps": job["steps"], "cfg": 1.0, "sampler_name": "euler",
                             "scheduler": "simple", "denoise": job["denoise"]}}
    pid = generate.request(f"{server}/prompt", {"prompt": graph, "client_id": uuid.uuid4().hex})["prompt_id"]
    while True:
        entry = generate.request(f"{server}/history/{pid}").get(pid)
        if entry and entry.get("status", {}).get("completed"):
            img = [i for o in entry["outputs"].values() for i in o.get("images", [])][0]
            url = f"{server}/view?filename={img['filename']}&subfolder={img.get('subfolder', '')}&type=output"
            with urllib.request.urlopen(url, timeout=60) as r:
                return Image.open(__import__("io").BytesIO(r.read())).convert("RGB")
        if entry and entry.get("status", {}).get("status_str") == "error":
            sys.exit("repaint failed: " + json.dumps(entry["status"].get("messages", []))[:2000])
        time.sleep(1)


def hair_mask(region, soft):
    """0..1 mask of light hair strands that cross into the eye from outside, so the repaint stays behind them.

    Light, low-saturation pixels are grouped into connected regions; only regions that also reach outside the
    repaint ellipse count as hair (old catchlights inside the iris are isolated and get repainted).
    """
    rgb = np.asarray(region, np.int16)
    light = (rgb.max(axis=2) > 195) & ((rgb.max(axis=2) - rgb.min(axis=2)) < 70)
    labels, count = ndimage.label(light)
    outside = np.asarray(soft) < 8
    keep = np.unique(labels[outside & light])
    hair = np.isin(labels, keep[keep > 0])
    hair = ndimage.binary_dilation(hair, iterations=3)
    return ndimage.gaussian_filter(hair.astype(np.float32), 1.5).clip(0, 1)


def lid_mask(region, soft, r):
    """0..1 mask of dark lash / eyelid / iris-outline strokes that reach into the repaint area from outside.

    The top of an anime iris usually sits under the upper eyelid; without this the repaint paints over the lashes.
    Only the outer band of the iris (within 0.35 r of its edge) is protected, so the old pupil outline, which may
    touch the lashes, is still repainted.
    """
    rgb = np.asarray(region, np.int16)
    dark = rgb.max(axis=2) < 100
    labels, _ = ndimage.label(dark)
    inside = np.asarray(soft) >= 8
    keep = np.unique(labels[~inside & dark])
    lids = np.isin(labels, keep[keep > 0]) & (ndimage.distance_transform_edt(inside) < 0.35 * r)
    lids = ndimage.binary_dilation(lids, iterations=1)
    return ndimage.gaussian_filter(lids.astype(np.float32), 1.0).clip(0, 1)


def restore_overlay(base, source, spec):
    """Copy an occluder (glasses reflection, translucent strand) from `source` back over the repainted eye.

    spec: {"box": [x0, y0, x1, y1], "color": [r, g, b], "tol": 38, "above": [[xa, ya], [xb, yb]]}
    Pixels inside box whose source color is within tol of color are restored; "above" optionally keeps only
    pixels above the line through the two points (image coordinates), e.g. the lower edge of a lens reflection.
    """
    x0, y0, x1, y1 = spec["box"]
    src = np.asarray(source, np.float32)[y0:y1, x0:x1]
    out = np.asarray(base, np.float32).copy()
    sel = np.linalg.norm(src - np.array(spec["color"], np.float32), axis=2) < spec.get("tol", 38)
    if "above" in spec:
        (xa, ya), (xb, yb) = spec["above"]
        yy, xx = np.mgrid[y0:y1, x0:x1]
        sel &= yy < ya + (xx - xa) * (yb - ya) / (xb - xa)
    sel = ndimage.binary_closing(sel, iterations=2)
    alpha = ndimage.gaussian_filter(sel.astype(np.float32), 1.2)[..., None]
    out[y0:y1, x0:x1] = out[y0:y1, x0:x1] * (1 - alpha) + src * alpha
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--job", required=True)
    parser.add_argument("--server", default="http://127.0.0.1:8288")
    parser.add_argument("--preview", action="store_true",
                        help="only compute masks and guides and write the check images; no repaint, no output image")
    args = parser.parse_args()
    job = {"seed": 1, "denoise": 0.6, "steps": 10, "loras": [["kieed_v1_epoch20.safetensors", 0.6]],
           **{k: generate.BACKENDS["krea2"][k] for k in ("unet", "clip", "vae")},
           **json.loads(Path(args.job).read_text(encoding="utf-8-sig"))}
    base = Image.open(job["image"]).convert("RGB")
    original = base.copy()
    eyes = job["eyes"]
    kinds = {e.get("kind"): e for e in eyes}
    if "light" in kinds and "dark" in kinds:
        # Head tilt from the line between her right (light) and left (dark) eye, so the drops point to her forehead.
        lt, dk = kinds["light"], kinds["dark"]
        tilt = float(np.degrees(np.arctan2(-(dk["cy"] - lt["cy"]), dk["cx"] - lt["cx"])))
        for e in eyes:
            e.setdefault("angle", round(tilt, 1))
    check_dir = Path(job.get("check_dir", Path(job["out"]).parent / "check"))
    check_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(job["out"]).stem
    for n, eye in enumerate(eyes):
        # r = horizontal iris radius, ry = vertical radius (defaults to 1.1 r), measured on the ORIGINAL image.
        # In the default "region" mode they only need to be roughly right: the repaint area is grown from the
        # drawn outline itself (see iris_region) and the check image shows its boundary for review.
        cx, cy, r = eye["cx"], eye["cy"], eye["r"]
        ry = eye.get("ry", r * 1.1)
        half = int(max(r, ry) * CROP_SCALE)
        box = (cx - half, cy - half, cx + half, cy + half)
        k = WORK / (2 * half)
        crop = original.crop(box).resize((WORK, WORK), Image.LANCZOS)
        use_region = eye.get("mask", job.get("mask", "region")) == "region"
        region = hair = None
        if use_region:
            region, hair, fit = iris_region(original, eye, box)
            for poly in eye.get("keep", []):  # areas to leave untouched (hair strands, lashes), image coordinates
                keep_img = Image.new("L", region.shape[::-1], 0)
                ImageDraw.Draw(keep_img).polygon([(x - box[0], y - box[1]) for x, y in poly], fill=1)
                region &= np.asarray(keep_img) == 0
            for poly in eye.get("add", []):  # extra areas to repaint, image coordinates
                add_img = Image.new("L", region.shape[::-1], 0)
                ImageDraw.Draw(add_img).polygon([(x - box[0], y - box[1]) for x, y in poly], fill=1)
                region |= np.asarray(add_img) > 0
            hair &= region
            drop_shift = eye.get("drop_shift", float(np.clip(fit["top"] + 0.92, 0, 0.45)) if fit["top"] > -0.78 else 0.0)
            warn = []
            if fit["fit_share"] < 0.4:
                warn.append("no clear iris outline found: the measured ellipse is used, check cx/cy/r")
            if not 0.8 <= fit["scale"] <= 1.2:
                warn.append("fitted outline differs a lot from the measured r: check the boundary")
            if fit["width"] < 0.8:
                warn.append("region narrower than the iris: part of it was not reached (add 'seeds')")
            print(f"eye {n} ({eye.get('kind')}): angle {eye.get('angle', 0.0)}, outline fit {fit['fit_share']:.2f}, "
                  f"fit/measured {fit['scale']:.2f}, width {fit['width']:.2f}, area {fit['area']:.2f}, "
                  f"lid top {fit['top']:.2f}, drop shift {drop_shift:.2f}, hair {fit['hair']:.2f}, "
                  f"center ({fit['cx'] + box[0]:.1f}, {fit['cy'] + box[1]:.1f}) r {fit['r']:.1f}/{fit['ry']:.1f}"
                  + "".join("\n  WARNING: " + w for w in warn))
            region_work = np.asarray(Image.fromarray(region.astype(np.uint8) * 255).resize((WORK, WORK),
                                                                                         Image.BILINEAR)) > 127
            hair_work = np.asarray(Image.fromarray(hair.astype(np.uint8) * 255).resize((WORK, WORK),
                                                                                     Image.BILINEAR)) > 127
            mask = Image.fromarray(ndimage.binary_dilation(region_work, iterations=2).astype(np.uint8) * 255)
            gcx, gcy, grx, gry = fit["cx"] * k, fit["cy"] * k, fit["r"] * k, fit["ry"] * k
        else:
            mask = Image.new("L", (WORK, WORK), 0)
            gcx = gcy = WORK / 2
            grx, gry = r * k * MASK_SCALE, ry * k * MASK_SCALE
            drop_shift = eye.get("drop_shift", 0.0)
            ImageDraw.Draw(mask).ellipse((gcx - grx, gcy - gry, gcx + grx, gcy + gry), fill=255)
        prompt = eye.get("prompt") or EYE_PROMPTS[eye["kind"]]
        pass_job = {**job, "seed": eye.get("seed", job["seed"])}
        guide = None
        if eye.get("guide", job.get("guide", True)) and eye.get("kind") in GUIDE_COLORS:
            # Paint the exact design first, then repaint lightly so only the rendering changes.
            guide = draw_guide(crop, eye["kind"], grx, gry, eye.get("angle", 0.0), (gcx, gcy),
                               region_work if use_region else None, drop_shift)
            pass_job["denoise"] = job.get("guide_denoise", 0.45)
        if args.preview:
            if use_region:
                check_image(crop, region_work, guide, None, check_dir / f"{stem}_eye{n}_preview.png", hair_work)
            continue
        out = repaint(args.server, guide or crop, mask, prompt, pass_job, n).resize((2 * half, 2 * half),
                                                                                    Image.LANCZOS)
        if use_region:
            if hair.any():
                # Put the translucent hair back over the new iris with the opacity it had over the old one.
                o = np.asarray(original.crop(box), np.float32)
                al = hair_alpha(o, hair, fit["hair_color"], fit["iris_under"])[..., None]
                out = Image.fromarray((np.asarray(out, np.float32) * (1 - al) + fit["hair_color"] * al)
                                      .clip(0, 255).astype(np.uint8))
            # Paste only inside the iris region; outline, lids, lashes, brows and everything outside it keep their
            # original pixels exactly (the feather stays inside the region).
            soft = ndimage.gaussian_filter(region.astype(np.float32), 0.6) * region
            soft = Image.fromarray((soft * 255).astype(np.uint8))
        else:
            soft = mask.filter(ImageFilter.GaussianBlur(WORK / 40)).resize((2 * half, 2 * half), Image.LANCZOS)
            keep = np.zeros(soft.size[::-1], np.float32)
            # Per-eye "keep_hair" / "keep_lids" override the job-wide setting (one eye under a lens or hair).
            if eye.get("keep_hair", job.get("keep_hair", True)):
                keep = np.maximum(keep, hair_mask(original.crop(box), soft))
            if eye.get("keep_lids", job.get("keep_lids", True)):
                keep = np.maximum(keep, lid_mask(original.crop(box), soft, min(r, ry)))
            soft = Image.fromarray((np.asarray(soft, np.float32) * (1 - keep)).astype(np.uint8))
        before = base.crop(box)
        base.paste(out, box[:2], soft)
        if use_region:
            result = base.crop(box).resize((WORK, WORK), Image.LANCZOS)
            check_image(crop, region_work, guide, result, check_dir / f"{stem}_eye{n}.png", hair_work)
            # Strict check: nothing outside the region may change.
            changed = np.abs(np.asarray(base.crop(box), np.int16) - np.asarray(before, np.int16)).max(2)
            if (changed[~region] > 0).any():
                sys.exit(f"eye {n}: pixels outside the region changed ({int((changed[~region] > 0).sum())})")
    if args.preview:
        print("preview written to", check_dir)
        return
    for spec in job.get("restore", []):
        base = restore_overlay(base, Image.open(spec.get("source", job["image"])).convert("RGB"), spec)
    Path(job["out"]).parent.mkdir(parents=True, exist_ok=True)
    base.save(job["out"])
    print(job["out"])


if __name__ == "__main__":
    main()
