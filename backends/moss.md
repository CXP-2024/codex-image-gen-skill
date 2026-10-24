# 后端:moss(MOSS-Image SFT)

## 模型

- 模型:`H:\models\diffusion_models\moss_image_sft_int8_convrot.safetensors`(OpenMOSS,5B 单流 DiT,SFT 版,int8)
- 文本编码器:`H:\models\text_encoders\qwen3.5_9b_int8_convrot.safetensors`(Qwen3.5 9B,`clip_type` = `moss_image`)
- VAE:`H:\models\vae\flux2-vae.safetensors`;空 latent 用 `EmptyFlux2LatentImage`(128 通道,16 倍下采样)
- 来源:Hugging Face `Comfy-Org/MOSS-Image`,2026-10-16 发布,Apache-2.0(模型和图片都可商用)
- 需要 ComfyUI ≥ 0.42.0(`H:\ComfyUI-latest` 是 0.42.1)
- 知识截止未公开

## 格式差异

- **括号不转义**:ComfyUI 的 MOSS 分词器关闭了权重解析(`comfy/text_encoders/qwen35.py` 里 `disable_weights=True`),文本原样送进 Qwen3.5。写 `furina (genshin impact)`;`(tag:1.5)` 这种权重语法也不会生效,只会变成字面文字,不要用。
- 官方推荐标签顺序:Quality → Score → Meta → Year → Character → Series → Artist → General,例:`best quality, highres, hatsune miku, vocaloid, 1girl, blue hair`。
- 支持纯自然语言和标签+自然语言混写,提示词最长约 4K token。英文效果最好,中文也支持;要在图里渲染文字时写进引号,换行用 `\n`。
- **不要指望 `@画师`**:实测加 `@yoneyama mai` / `@wlop` 与不加几乎同图。画风靠自然语言描述(如 `soft painted shading, airbrushed highlights, fine linework`)。
- 质量前缀:`best quality, highres, newest, safe`。

## 负面核心

```
nsfw, worst quality, low quality, bad anatomy, bad hands, watermark, jpeg artifact, signature, text
```

(官方推荐 `nsfw, worst quality, bad anatomy, watermark, jpeg artifact`,上面多加了手部和文字。)

## 参数(`generate.py` 默认)

- 896×1344,50 步,CFG 3.5,`euler` + `simple`(模型自带 shift 5.0)
- 官方建议:总像素 1M / 1.5M / 2M(可到 0.25M–4M),边长是 16 的倍数;≥ 50 步;CFG 3.0–6.0,短提示词调高。
- SLG(skip layer guidance):job 里写 `"slg": 3.0` 打开(单层 22,0.01–1.0)。官方说关掉 SLG 会更写实但细节可能崩。**本地还没对比测过开关差异。**
- 速度:RTX 5080 上 896×1344、50 步约 30 秒/张。

## 实测结论(2026-10-21,seed 2468 / 4680)

- 只写"名字+作品":芙宁娜 ✅(连礼帽、领结、宝石扣都对)、初音 ✅(自动是经典服装+耳麦)、丰川祥子 ✅(编发、黑丝带、黄瞳)、奥黛塔 ❌(画成金发的通用原神角色)。
- 插画场景(雪地石板路+藤蔓边框)比 Anima 丰富:人物更大、有厚涂和纵深;但仍偏常见的"AI 二次元"质感。
- `@画师` 几乎无效(见上)。

## 生态

- LoRA 训练:[KohakuMossTrainer](https://github.com/KohakuBlueleaf/KohakuMossTrainer)(最低约 6GB 显存)、[DiffSynth-Studio](https://github.com/modelscope/DiffSynth-Studio)
- 社区:8 步蒸馏 `lodestones/MOSS-Image-SFT-8-steps-dmd`、去竖条纹 LoRA `MATLOWAI/MOSS-Image-SFT-DeBand`(都未在本地测试)
