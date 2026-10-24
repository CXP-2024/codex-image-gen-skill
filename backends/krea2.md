# 后端:krea2(Krea 2 Turbo,可用参考图)

## 模型

- 模型:`H:\models\diffusion_models\krea2_turbo_int8_convrot.safetensors`(Krea 2 Turbo,12B DiT,8 步蒸馏)
- 文本编码器:`H:\models\text_encoders\qwen3vl_4b_fp8_scaled.safetensors`(Qwen3-VL 4B,`clip_type` = `krea2`)
- VAE:`H:\models\vae\qwen_image_vae.safetensors`(和 Anima 同一个文件)
- LoRA:`krea2_style_reference.safetensors`(ostris 的风格参考 LoRA,1–2 张参考图)、`krea2_retroanime.safetensors`(触发词 `purple retro anime style`)
- 来源:Hugging Face `Comfy-Org/Krea-2`;许可 Krea 2 Community License:可以商用的前提是公司全年总收入 < 100 万美元,超过要另买企业许可
- ComfyUI 0.42.1 原生支持,只用核心节点

## 两种模式(`generate.py` 自动切换)

- **纯文本**:job 里不写 `style_images`。`CLIPTextEncode` + `KSampler`,8 步,CFG 1,`euler`/`simple`,负面条件自动置零(写了 `negative` 也不生效)。
- **风格参考图**:job 里写 `"style_images": ["H:\\...\\ref.png"]`(1–3 张,官方说 1–2 张效果最好)。脚本会把图片上传到 ComfyUI,自动挂上 style reference LoRA,按官方蓝图走 `TextEncodeQwenImageEditPlus` → `FluxKontextMultiReferenceLatentMethod(index_timestep_zero)` → `CFGGuider` + `SamplerCustomAdvanced`,`ModelSamplingFlux`(max 1.15 / base 0.5)。`style_strength` 默认 1.0。
- 额外风格 LoRA:`"loras": [["krea2_retroanime.safetensors", 1.0]]`,并在提示词末尾加触发词。

```json
{"backend": "krea2", "prompt": "...", "style_images": ["H:\\MV_making\\assets\\img_styles_example\\test2.jpg"],
 "width": 1024, "height": 1536, "seed": null, "prefix": "krea2/furina_ref"}
```

用户收集的风格参考图在 `H:\MV_making\assets\img_styles_example\`(test1–test8)。

## 提示词

- 自然语言,不用 Danbooru 标签和 `@画师`;角色写"名字 + 作品 + 外观"。认识芙宁娜(只写名字也能还原服装)。
- 参考图模式下提示词只描述内容,不需要触发词,风格交给参考图。
- 尺寸 1K–2K,边长是 16 的倍数;默认 1024×1536。

## 默认画风与芙宁娜眼睛(2026-10-21)

- **默认画风**:`"style": "kieed"` = K2 Turbo + `kieed_v1_epoch20.safetensors`(Civitai 2635815 的 krea2 版)强度 1.0 + 两段式采样(768×1152 起,输出 1536×2304)。提示词用 8 段英文长描述(风格 / 构图姿势 / 环境 / 色光 / 材质 / 构图几何 / 粒子氛围 / 关键词)。
- **芙宁娜异色水滴瞳 K2 画不出来**:提示词写明、去掉 LoRA、用立绘当参考图(没有 Krea2EditRebalance 节点,出满屏噪点)都无效。修法是出图后**逐只眼局部重绘**,原理、参数、戴眼镜的处理见 `backends/local-repaint.md`。
- 带参考图的 job 可写 `"ref_mode": "character"`:只喂参考图、不挂风格参考 LoRA(实测没有 Rebalance 节点时效果崩,暂不推荐)。
- 两段式采样的社区配方:`"two_pass": true`(7 步出 768×1152 草稿 → latent bislerp 放大 2 倍 → 从第 4 步重采 10 步),来自 `H:\models\krea2_resources\Workflow\Krea2高清二次采样.json`。

## 电影感宽幅预设 `kieed_cinema`(2026-10-22)

从用户收集的 `img_styles_example\test13.png`(夜色小巷)和 `test14.png`(雪中玻璃温室)里读出的作者原始工作流(PNG 内嵌 ComfyUI `prompt`),本地按原 seed 复现,画风色调一致,细节不逐像素相同。

- **LoRA 栈**(都在 `H:\models\loras`):`Krea2_TextFusion_Refusal_Reduction` 0.8、`Krea_2_zidiusArt_Melancholy_v2` 0.3、`kieed_v1_epoch20` 0.65、`z3zz4-k2-4_c1-st5000` 0.45、`MSK_detailed_krea` 0.4。这些文件都没有文本编码器权重,只加载到模型即可。
- **触发词** `zidiusArt, MSK, `(预设自动加在最前)。
- **采样**:第一段 8 步 → latent bislerp ×2 → 第二段从第 4 步跑到第 8 步,第二段 seed = seed + 1;CFG 1,euler/simple。
- **ColorMatch**:`"color_match": 0.5`,用第一段小图的颜色校正高清结果(MKL 算法,`generate.py` 下载后用 numpy 做,不需要 KJNodes)。第一段小图另存为 `<prefix>_firstpass`。
- **画幅**:21:9 超宽。默认 1568×672(约 1MP,输出 3136×1344);温室原图是 2216×952(约 2MP,输出 4432×1904),job 里写 `width`/`height` 即可。
- **提示词写法**:一大段英文自然语言,按 镜头 / 人物 / 场景 / 光与渲染 / **色彩脚本** / 氛围 分段。色彩脚本用十六进制色值逐项指定区域颜色(如 `#0c1014 铁架最深阴影`、`#b2352c 红灯笼,画面唯一暖色`),这是两张图色调统一克制的关键。完整原文见 `img_styles_example\test13_工作流.txt`、`test14_工作流.txt`。
- **许可**:Melancholy 不允许出售生成的图;要商用就把它从 `loras` 里去掉(job 里写完整的 `loras` 覆盖预设)。

```json
{"style": "kieed_cinema", "prompt": "A cinematic 2D illustrated scene in widescreen ... Colour script: ...",
 "seed": null, "prefix": "krea2/cinema/xxx"}
```

复跑任何带工作流的 PNG(自动把常见第三方节点换成核心节点):

```powershell
python -I H:\MV_making\tools\repro_comfy_png.py <原图.png> <输出目录> [--prompt-file 新提示词.txt] [--seed N]
```

## 社区做法(2026-10-21 调研 Civitai 上 Krea 2 高赞图)

- 高质量二次元图几乎都是**长提示词 + 2K 以上分辨率**(常见 1152×2048、2304×3072,甚至 3328×4864),不是 1024 级短提示词。官方也说长而具体的提示词效果最好,可以按 `docs/expansion.txt` 的思路把短需求扩写:画风/媒介放最前,再写主体、服装、动作、场景、光、配色、构图。
- 风格靠描述"怎么画的"(线条、上色、笔触、颗粒、色差描边),不是写形容词。
- 社区常用二次元微调 **JanK2**(JANKU 的 Illustrious 数据微调 Krea 2 Turbo):本地已有 `H:\models\diffusion_models\JANK2_v1.0_INT8_CONVROT.safetensors`(来自 HF `janxd/JANk2`,SHA256 与 Civitai 一致),job 里写 `"unet": "JANK2_v1.0_INT8_CONVROT.safetensors"` 即可切换,其余参数不变。

## 复刻 test6–8 的实测(seed 2026,长提示词,1344×2016 / 1152×2048)

- 原版 Krea 2:内容和构图基本复刻(相纸白边、鲸鱼尾、防暴警察包围+激光),但上色偏平、偏干净,缺原图的厚涂层次和颗粒。
- JanK2:更"Illustrious 二次元"——赛璐璐、光泽更亮、对比更强,**离原图的绘画质感反而更远**。
- 结论:原图大概率还叠了风格 LoRA 或高清重绘,单靠底模+提示词到不了;速度 2K 单张 20–60 秒(显存紧时偶尔几分钟)。

## 实测结论(2026-10-21,seed 1357)

- 速度:纯文本约 12 秒/张;带参考图约 45 秒/张(含上传和编码)。
- 参考图主要迁移的是**配色、明度、背景处理和版式**(test1 → 白底淡彩;test2 → 奶油暖调;test6 → 连相纸白边都学了;test7 → 明亮蓝天),**线条和笔触几乎没变**,仍是 Krea 自己的干净动画质感。
- `style_strength` 1.5 会糊、出伪影,不要超过 1.0–1.2。
- 想要真正的个人笔触,需要用这批参考图训练风格 LoRA(Krea 2 官方说 LoRA 训练至少 12GB 显存、建议 64GB 内存;MOSS 可用 KohakuMossTrainer)。
