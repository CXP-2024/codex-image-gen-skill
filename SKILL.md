---
name: image-gen
description: |
  Generate anime illustrations, MV frames, and character or style tests with the user's local ComfyUI workflows in H:\MV_making. Default to Krea2 for anime illustration; read its backend guide before prompting or rendering. Includes Anima, MOSS, LoRA previews, reference images, and local region repair. Use for this user's anime illustration workflow, especially Krea2; honor any explicitly requested backend.
---

# 图像生成(多后端)

## Codex 同步与默认选择

- 来源：`H:\MV_making\.claude\skills\image-gen`，2026-10-24 同步到 `C:\Users\Administrator\.codex\skills\image-gen`。这是独立副本；未设置自动同步。
- **用户偏好：二次元插画主选择 Krea2 本地 ComfyUI 工作流**。未点名其他后端时，先读本目录 `backends/krea2.md`，使用 `backend: krea2`，按已有画风预设与用户本次要求选参数。
- 用户明确指定后端、画风或参考图时按其要求。Anima、MOSS 和 Codex 保留为备选；不因复杂场景就自动切换到 Codex。
- 下面第 2–4 节的 Danbooru 标签与负面词主要用于 Anima/MOSS；Krea2 使用后端说明中的英文自然语言提示词，其负面条件不生效。
- 脚本、`backends/`、`refs/` 和 `lora_gallery/` 均相对此技能目录定位。已有模型、ComfyUI、训练工具与项目参考素材继续使用原 H 盘路径，不复制模型或改动环境。


目标:把用户的需求写成所选后端能稳定执行的正/负提示词,需要出图时交给对应后端。默认 `safe`。

本文件是共用规则和后端选择;**每个后端的格式、参数和坑写在 `backends/<名字>.md`,选定后端后必须先读那一份再写提示词**。

## 成品审批与归档

- **只归档用户明确审批通过的最终完成图**。生成成功、助手检查通过、候选图被讨论或用户要求继续修图，都不等于归档批准；批准必须能对应到具体图片或版本。
- 芙宁娜（Furina）的成品目录：`H:\MV_making\assets\furina_img_gen`。
- 其他角色的成品放在 `H:\MV_making\assets\<角色名>_img_gen`，优先沿用该角色已有目录；新目录使用稳定的角色英文名或拼音，不同角色分别保存。多人图按用户指定的归档归属处理，未指定时先确认所属目录。
- 候选图、首次生成、修眼/修手中间图、局部裁切、遮罩、预览对比图继续保存在工作输出目录（默认 `H:\ComfyUI-latest\output` 或任务工作目录），不直接输出到角色成品目录。
- 用户批准后，将被批准的最终版本复制到角色成品目录，保留工作源文件及图片原有元数据；避免同名覆盖，使用可区分的文件名，并告知归档路径。后续修订是新版本，需要用户再次批准后才归档。
- 不把历史生成图片默认视为已批准，不批量补归档未经用户明确选择的旧图。

## 后端一览

| 后端 | 状态 | 强项 | 弱项 | 说明文件 |
|---|---|---|---|---|
| `anima` | 可用 | `@画师` 标签能控制画风(约 6 万画师);知识截止 2026-07 | 渲染偏平;只写名字时服装会乱;模型非商用 | `backends/anima.md` |
| `moss` | 可用 | 角色识别准(只写名字也能还原标志服装);渲染更丰富;Apache-2.0 可商用 | `@画师` 标签几乎无效;知识截止未公开 | `backends/moss.md` |
| `krea2` | 可用 | **支持风格参考图**(迁移配色/明度/版式);纯文本 12 秒/张;认识芙宁娜 | 参考图学不到笔触;没有负面词;收入 ≥ 100 万美元不能商用 | `backends/krea2.md` |
| `codex` | 可用 | 场景、光影、构图最丰富;自然语言理解最好;可附参考图 | 不能设尺寸/seed/负面词;消耗 Codex 用量;每张约 50–100 秒 | `backends/codex.md` |

### 怎么选
- **默认画风**(2026-10-21 起):`style: kieed` = K2 + kieed(Krea 2 版)单独使用 + 两段式采样,提示词用 8 段英文长描述(见 `backends/krea2.md`)。Anima 的 `style: natarapisu` / `style: kazutake` 保留为备选,不要混合 LoRA。
- **电影感宽幅**(2026-10-22 起):`style: kieed_cinema` = 社区作者的 5 LoRA 配方(kieed 0.65 + 氛围/细节 LoRA)+ 8+8 两段采样 + ColorMatch,21:9 超宽,提示词带十六进制色彩脚本。适合 MV 场景镜头、大场景小人物。详见 `backends/krea2.md`。含 Melancholy LoRA,不能卖图。
- **清爽粉彩(自训练)**(2026-10-24 起):`style: ura` = K2 + 自己训练的 ura 画风 LoRA(`ura_style_k2_000000900.safetensors`,80 张 Pixiv 71432148 作品,batch 4 × 900 步)+ 两段采样,触发词 `uraStyle` 由预设自动加。细线、淡阴影、圆脸大眼的白底插画。训练素材和配置在 `tools/k2_lora_cloud`(`README_ura_style.md`),云端镜像 `k2-lora-train`。不加触发词也会改变画风,不要时就别加载。
- **各 LoRA 长什么样**:看 `lora_gallery/LORA_GALLERY.md`(同提示词同 seed 的样图 + 触发词/许可/来源)。**`H:\models\loras` 里增删或重新测试 LoRA 时必须同步更新**:改 `lora_gallery/loras.json`,再运行 `python lora_gallery/build_gallery.py`(只补渲缺的样图,`--redo <id>` 强制重渲),文档和总览图会自动重建。新增画风预设时也在 json 里写上 `preset`。
- 用户点名后端 → 用点名的。
- 要**模仿某位画师/某种画风** → `anima`(只有它的 `@画师` 有效)。
- 要**角色还原准、画面精致**、或成品可能商用 → `moss`。
- 用户给了**参考图**要"这种感觉"(配色、明度、版式)→ `krea2` 的参考图模式;用户收集的参考图在 `H:\MV_making\assets\img_styles_example\`。
- 要**复杂场景/氛围、一张成品级插画**,或想拿参考图引导 → `codex`(先确认用户愿意消耗 Codex 用量;要固定 seed 复现时不要用它)。
- 两个都不认识的角色(实测:奥黛塔)→ 任一后端都只能靠外观描述或 LoRA,先告诉用户这一点。
- 拿不准时两个各出一张给用户比较。

## 1. 先理解画面,再写词

动笔前在心里定下(不必输出给用户):

1. **谁**:角色、人数、作品
2. **在做什么**:一个最有张力的瞬间——起因 → 角色反应 → 看得见的后果。单人图也要有内在张力(风吹起头发她伸手按住、低头看信纸时指尖发紧)。
3. **镜头**:景别(close-up / upper body / cowboy shot / full body)+ 视角(eye-level / from above / from below)
4. **光**:光源方向和类型
5. **画布**:按构图选比例,不默认竖图

用户已给完整构图时照用;描述模糊时自行补一个合理情境,不改写用户明确给出的场景。主体要占画面足够比例——全身构图再加大边框,人物会小到看不清细节。

## 2. 提示词结构(Anima / MOSS)

```
[质量/年代/安全] → [人数] → [角色, 作品] → [@画师] → [外貌/服装标签] → [动作/氛围短语] → [自然语言句子]
```

分三层写,同一语义只出现在一层:

| 层 | 内容 | 写法 |
|---|---|---|
| **标签** | 质量、安全、人数、角色、作品、画师、发色瞳色发型、服装、道具、单一姿势/表情/场景 | Danbooru 标签,小写+空格,逗号分隔 |
| **短语** | 动作、情绪、天气效果、画风倾向 | 短英文短语,如 `strong wind, petals filling the air` |
| **句子** | 空间位置、动作归属、手和道具的接触、视线、遮挡、光源、景深、色彩、因果后果 | 完整英文句子,放在最末尾 |

- 小写、空格分词:`red hair`,不写 `red_hair`(分数标签如 `score_7` 例外)。
- **括号的写法因后端而异**(Anima 要转义,MOSS 不转义),见各后端文件。
- 角色名**后面紧跟作品名**:`furina (genshin impact), genshin impact`,否则容易串角色。
- 同类外观标签只留最能识别角色的 2–4 个,不穷举、不重复。
- 越详细越好但不要堆:太短背景单调;自然语言一般 3–6 句,每句都要改变画面,不写世界观、心理活动、文学比喻。
- 安全标签:`safe` / `sensitive` / `nsfw` / `explicit`。**默认 `safe`**;用户明确要求才改为 `sensitive`。

## 3. 角色处理

- 中文名先换成 Danbooru 规范标签:芙宁娜 → `furina (genshin impact)`,初音未来 → `hatsune miku`(作品 `vocaloid`),丰川祥子 → `togawa sakiko`(作品 `bang dream! it's mygo!!!!!` 或 `bang dream! ave mujica`)。不确定时联网查 Danbooru wiki,不要编造标签。
- 补 2–4 个外观锚点(发色、瞳色、发型、标志服装/配饰),并**写明服装**(Anima 只写名字时服装会变成随机便装)。
- 新角色认不出(实测 2026-10-21:奥黛塔在 Anima-2.9B 和 MOSS-Image 上都不认识)→ 去掉角色名,改纯外观描述,或用 LoRA。
- 多角色:人数标签(`2girls`)+ 每个角色名;在句子层逐个绑定位置与外观:`Place Furina on the left, with ...`。属性不能跨角色串。

## 4. 负面提示词

各后端有自己的核心负面词(见后端文件),再按画面追加:

| 场景 | 追加 |
|---|---|
| 头像/半身/表情 | `bad eyes, asymmetrical eyes, deformed face` |
| 全身/立绘 | `extra limbs, missing limbs, bad feet` |
| 动作/战斗/跳跃 | `extra limbs, broken joints, disconnected limbs` |
| 手持道具/手部特写 | `fused fingers, malformed hands` |
| 双人近距离 | `merged bodies, extra arms, cloned face` |
| 3 人以上 | `duplicate, merged bodies, cloned face, same outfit` |
| 不需要文字 | `text` |
| 偏写实时 | `photorealistic, 3d` |

有景深/背景虚化时,不写全局 `blurry`,改为 `blurry face`。

## 5. 冲突检查(输出前)

- `solo` 与多人只留一个;景别、视角、朝向各只留一个
- `closed eyes` 与 `looking at viewer` 不共存
- 光源与场景同一空间;背光时补一句脸部补光
- 远景不要求表情细节;标签层与句子层不重复同一外观

## 6. 输出格式

先给用户:

```
后端:<krea2 / anima / moss / codex>
正向:<prompt>
负向:<negative>(krea2 / codex 省略)
参数:<width>×<height>,<steps> 步,CFG <cfg>,<sampler>/<scheduler>,seed <seed 或 随机>(codex 只写画幅)
```

## 7. 出图

### 本地 ComfyUI(`krea2` / `anima` / `moss`)

- ComfyUI:`H:\ComfyUI-latest`(v0.42.1,同时支持 Anima 和 MOSS),模型通过 `extra_model_paths.yaml` 读 `H:\models`。
- 这份 ComfyUI 的 venv 只装了少量新包,PyTorch 等依赖经 `.venv\Lib\site-packages\zz_shared_minimaxh3.pth` 复用 `H:\MiniMaxH3\.venv`;不要在其中 `pip install` 会改动 torch 的包。`H:\MiniMaxH3\ComfyUI`(0.37.0)留给 MiniMax H3 工作流,不要升级它。
- 确认 `http://127.0.0.1:8288` 在运行;没在运行就在后台启动:

```powershell
Set-Location H:\ComfyUI-latest; & H:\ComfyUI-latest\.venv\Scripts\python.exe main.py --listen 127.0.0.1 --port 8288
```

- 端口用 8288:本机 Windows 把 8170–8269 保留给了 Hyper-V/WinNAT,绑 8188 会报 WinError 10013。保留范围每次开机可能变化,报同样错误时用 `netsh interface ipv4 show excludedportrange protocol=tcp` 查,换端口并给 `generate.py` 传 `--server`。
- 16GB 显存一次只跑一个 ComfyUI 实例。

把参数写成 UTF-8(无 BOM)JSON,未写的字段用该后端的默认值:

```json
{"backend": "moss", "prompt": "...", "negative": "...", "width": 896, "height": 1344,
 "seed": null, "batch": 1, "prefix": "moss/furina_test"}
```

```powershell
python <skill目录>\generate.py --job job.json
```

脚本只用 ComfyUI 核心节点,等待完成后打印后端、图片路径和实际 seed;用 Read 查看图片后再向用户汇报。同一提示词要多张变体用 `batch`,不同提示词分别提交。

### Codex(`codex`)

不经过 ComfyUI:用 `codex_generate.py`,提示词写自然语言,见 `backends/codex.md`。输出同样放在 `H:\ComfyUI-latest\output\<prefix>_00001_.png`。

### 出图后修细节

小细节画错不重出整张,只修那一块。**芙宁娜的图出完都要修眼睛**(K2 画不出她的异色水滴瞳)。

- **眼睛(默认,用户认可)**:`codex_eye_edit.py`。每只眼裁出放大 → Codex 按官方眼睛参考(`refs/furina_eye_*.png`)+ kieed 画风参考(`refs/kieed_eye_style.png`)改虹膜 → 只把虹膜区域贴回原图,眼睑、睫毛、头发保持原像素。每只眼一次 Codex 调用(约 45 秒,耗用量);Codex 结果有缓存,改贴回区域(`add` / `cut` 多边形)不用重调。镜中倒影左右要对调(`"mirror": true`)。
- **人物太小、脸或手崩坏**:`region_redraw.py`。框住人物 → 放大 3 倍 → 同画风 LoRA 低噪点重绘(denoise 0.4 起,多给几个 seed)→ MKL 校色 + `lowfreq` 保留原图大色块 → 羽化贴回。
- **单个小物件画坏(手、道具)**:`codex_region_edit.py`。方框裁出放大 → Codex 按指令只改那一处、保持画风 → MKL 校色 → 只在椭圆/多边形遮罩内羽化贴回。实测 07 玫瑰窗的手套:只写"自然、优雅、五指"时 Codex 画成了写实的细长手,和画风不搭;给它一张同画风的手做参考(`refs`),并写明"短小、和袖口一样宽、平涂、不要写实解剖"后才对。**改手、改脸这类会重画整块的编辑一定要给画风参考**:裁出同一张图里画风对的部分(哪怕结构是错的,比如原来画错的那只手)放进 `refs`,并设 `"ref_role": "style"`;不给的话 Codex 会画成自己的干净细线风格,和原图明显不搭(温室两张的手实测)。K2 低强度重绘不适合给 Codex 的结果"补画风":0.3–0.4 会把手画得斑驳、线条断裂。**改手前先让用户确认每根手指是哪根**,不要自己推:我和 Codex(gpt-6.1-sol)按解剖推了好几轮都认错。用户给的判读(温室两张举手接雪):从左到右是食指、中指、无名指、小拇指,最右边单独分开、靠脸的是拇指。确认后在提示词里按"从左到右第几根"写明要改哪根,遮罩只盖那一根并留出新指尖的位置(遮罩切到指尖会贴出半透明的残指)。
- 旧方法 `eye_fix.py`(程序画草图 + K2 低噪点重绘)保留作离线备选,原理见 `backends/local-repaint.md`。

### 其他后端

见对应 `backends/*.md`。

## 加新后端

1. 在 `backends/` 写一份 `<名字>.md`:模型文件、提示词格式差异、推荐参数、实测结论(写日期)。
2. 走本地 ComfyUI 的:在 `generate.py` 的 `BACKENDS` 里加一项默认参数(模型文件、`clip_type`、`latent` 节点等);图结构不同时再扩展 `build_graph`。
3. 不走 ComfyUI 的(如 Codex CLI):在后端文件里写清调用命令和输出位置,需要时另写脚本。
4. 更新上面的「后端一览」和「怎么选」。
