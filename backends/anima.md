# 后端:anima(Anima-2.9B)

## 模型

- 模型:`H:\models\diffusion_models\Anima-2.9B-preview-v1.safetensors`(社区版 Gazingstars123/Anima-2.9B,40 层,~2.9B,bf16)
- 文本编码器:`H:\models\text_encoders\qwen_3_06b_base.safetensors`(Qwen3 0.6B,`clip_type` = `stable_diffusion`)
- VAE:`H:\models\vae\qwen_image_vae.safetensors`
- 知识截止:2026 年 7 月(2.9B 新增数据);原版 Anima 截止 2025 年 9 月
- 许可:模型非商用(CircleStone Labs Non-Commercial);生成的图片可商用
- ComfyUI ≥ 0.33 才能按权重正确识别 40 层(`comfy/model_detection.py` 用 `count_blocks`),更旧的版本会静默截成 28 层

## 格式差异

- **标签里的括号要转义**:ComfyUI 对 Anima 解析权重语法,`furina (genshin impact)` 会被剥掉括号、内部加权 1.1。写成 `furina \(genshin impact\)`;写进 JSON 文件时反斜杠再转义一次(`"furina \\(genshin impact\\)"`)。只有真要加权时才用不转义的 `(tag:1.5)`。
- **画师**:写 `@名字`,放在角色之后、外貌之前;一张图默认最多 1 个画师。不加 `@` 几乎无效。带括号的画师名同样转义:`@lam \(ramdayo\)`。改名的画师用 2025 年 9 月前的旧名。
- 挑画风:[animastyles.thetacursed.com](https://animastyles.thetacursed.com/)、[anima.mindspark.fyi](https://anima.mindspark.fyi/)、[animterest](https://kellenok.github.io/animterest/index.html)(以图搜画风)。站点都是 Anima 1.0 渲染。
- 以图找画师:`H:\models\kaloscope\identify_style.py <图片>`(Kaloscope 2.0,39,260 位 Danbooru 画师),用 `H:\models\kaloscope\.venv\Scripts\python.exe` 运行;结果要再核对画师是否在 Anima 的画师表里。
- 质量前缀:`masterpiece, best quality, newest, year 2026, safe`。2.9B 训练数据不含 score 标签,默认不写。旧番风去掉 `newest`,换成 `year 2005` 之类。
- 权重:ComfyUI 对 Anima 的 Qwen3 分支强制权重为 1.0,只有 T5 分支带权重(`comfy/text_encoders/anima.py`),加权效果比 SDXL 弱。默认不加;某元素不出现时才从 `(tag:1.5)`–`(tag:2)` 起,一张图最多 1–3 处,不给角色名、画师、安全标签加权。

## 画风预设(用户选定,2026-10-21)

用户试过 5 个画师 LoRA 和 4 种混合后,**只要单独的 na_tarapisu153 或 kazutake hazano,不要混合**(混合后两者的特点都被冲淡)。job 里写 `"style"` 即可,`generate.py` 自动设好底模、LoRA、触发词、高清重绘和负面词:

| `style` | 画风 | 底模 | LoRA(强度) | 触发词 |
|---|---|---|---|---|
| `natarapisu` | 轻快的手绘线条感、留白、平涂 | `anima-base-v1.0.safetensors` | `na_tarapisu153_style_v1.safetensors` (1.0) | `@na tarapisu153` |
| `kazutake` | 淡雅通透、低饱和、光感干净 | `anima-base-v1.0.safetensors` | `kazutake-hazano_v2_epoch28.safetensors` (1.0) | `@4x0style, @kazutake hazano` |

```json
{"style": "natarapisu", "prompt": "masterpiece, best quality, very aesthetic, newest, year 2025, safe, 1girl, ...", "seed": null, "prefix": "anima/xxx"}
```

- 预设固定:32 步、CFG 4.5、832×1216 起步、1.5 倍高清重绘(denoise 0.45、20 步)→ 输出 **1248×1824**,单张约 36 秒;负面词自动加 `signature, artist name, twitter username`。
- 用的是**原版 Anima Base v1.0**(这些 LoRA 训练在 28 层原版上),不是 2.9B;要在 2.9B 上用需装层映射节点,未测。
- LoRA 来源:Civitai 2922938(na_tarapisu153,不可商用出图)、2210902 的 Anima v2.0(kazutake hazano,不可商用出图)。MV 若要盈利,需换允许商用的画风或自训。
- 精细度:2 倍重绘(1664×2432)发丝更多但眼周装饰会错位,不稳;要 4K 帧建议 1.5 倍出图后再接动漫超分模型(未下载)。
- 构图:横版大场景里人物容易变小,写 `cowboy shot` + "fills most of the frame / close to the viewer"。

## 移植 NovelAI 画师串

用户的参考图里有 NovelAI V4.5 出的图(test2.jpg 的 JPEG 注释、test5.png 的 `Comment` 字段里带完整提示词)。拿到这类提示词时:

- 去掉 NovelAI 权重语法(`1.25::xxx::`、`[[...]]`、`-2::...::`),画师改成 `@名字`(下划线换空格、括号转义),先确认画师在 Anima 画师表里。
- 实测(2026-10-21):test5 的 11 位画师全部保留时,厚涂、发丝、肤色质感明显接近原图;只留权重最高的 3 位反而更平。test2 的画师串出得来米山舞式的平涂与色差描边,但饱和度比原图高,需要加 `muted colors` / `pastel colors` 之类压一压。
- 这是目前**最接近用户喜欢的手绘感**的开源做法。

## 负面核心

```
worst quality, low quality, lowres, bad anatomy, bad hands, extra fingers, missing fingers, watermark, logo, signature, nsfw
```

不写 `score_1` 等分数标签(2.9B 未训练)。

## 参数(`generate.py` 默认)

- 832×1216,30 步,CFG 4.5,`euler` + `sgm_uniform`,`EmptyLatentImage`
- 其他推荐尺寸:1152×1536(带环境)、1024×1024、1216×832(双人横向)、1344×768(MV 横屏)。1536×1536 作者标注不稳定。
- 追求质量用 50 步;构图不理想时试 `res_multistep` + `linear_quadratic`;CFG 3.5–5,不超过 7。

## 实测结论(2026-10-20 / 21)

- 只写"名字+作品":芙宁娜、初音、祥子的发型瞳色发饰对,服装随机且偏紧身;写明服装后能还原。奥黛塔不认识。
- `@画师` 有效,但场景/光影描述写得很细时画风差异会被压住;想看画风差异就少写光影。
- 渲染偏平、线稿感重;全身构图人物容易太小。
- **芙宁娜的眼睛 Anima 能直接画对**(2026-10-22):`anima-base-v1.0` + `kieed_v1.safetensors`(kieed 的 **Anima 版**,无触发词)1.0 + `@kieed`,标签写 `heterochromia, blue eyes, light blue eyes, drop-shaped pupils, mismatched pupils`,两张测试图都一次出对异色水滴瞳,左右也对,不用 `eye_fix.py`。K2 不认识这个设计(只能后期修),原因是 Anima 用 Danbooru 训练,这些标签在芙宁娜的图上大量出现。

## 示例

**需求:**"芙宁娜在歌剧院后台,演出结束后独自卸下帽子,有点落寞"

```
后端:anima
正向:masterpiece, best quality, newest, year 2026, safe, 1girl, solo, furina \(genshin impact\), genshin impact, white hair, streaked hair, blue eyes, top hat, holding hat, sitting, backstage, dressing room mirror, tired smile, quiet melancholy, warm vanity lights, Place her seated in front of a lit vanity mirror, slightly left of center, holding her top hat in both hands on her lap. Light her face from the mirror bulbs with a warm glow, leaving the backstage corridor behind her in dim blue shadow. Keep her reflection faintly visible in the mirror and her face sharp and readable.
负向:worst quality, low quality, lowres, bad anatomy, bad hands, extra fingers, missing fingers, watermark, logo, signature, bad eyes, deformed face, fused fingers, text, nsfw
参数:832×1216,30 步,CFG 4.5,euler/sgm_uniform,seed 随机
```
