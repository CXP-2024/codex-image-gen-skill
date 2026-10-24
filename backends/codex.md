# 后端:codex(Codex CLI 内置 image_gen)

## 机制

- 本机 Codex CLI 0.162.1(`codex` 在 PATH 上,`C:\Users\Administrator\AppData\Roaming\npm\codex.CMD`),`image_generation` 功能已开启。
- `codex exec` 里的 agent 调用 Codex 自带 `imagegen` skill(`~\.codex\skills\.system\imagegen\SKILL.md`)的 **内置 `image_gen` 工具**:走用户的 Codex 登录,**不需要 `OPENAI_API_KEY`**,会消耗用户的 Codex 用量(实测一次约 2.2 万 token)。具体图像模型工具不公开。
- 图片保存在 `~\.codex\generated_images\<会话 ID>\exec-<ID>.png`;内置工具**没有尺寸、质量、seed 参数**,也没有输出路径参数。
- 另有 CLI 兜底模式(`scripts/image_gen.py`,`gpt-image-2`,可设 `size`/`quality`),需要 `OPENAI_API_KEY`,按 API 计费——**只有用户明确要求时才用**,本 skill 没有接。

## 调用

用本目录的 `codex_generate.py`(只读沙箱运行 `codex exec --json`,按会话 ID 找新图,复制出来):

```powershell
python <skill目录>\codex_generate.py --prompt "<自然语言提示词>" --prefix codex/furina_stage
python <skill目录>\codex_generate.py --job job.json
```

```json
{"prompt": "...", "count": 1, "images": ["H:\\path\\to\\reference.png"], "prefix": "codex/furina_stage"}
```

- `count`:同一提示词要几张(每张单独一次 image_gen 调用)。
- `images`:参考图(风格/构图/角色参考),通过 `codex exec -i` 附上;**还没实测参考图效果**。
- 输出:`H:\ComfyUI-latest\output\<prefix>_00001_.png`,和本地后端放在一起;脚本打印会话 ID、耗时、原始路径和复制后的路径。
- 不经过 ComfyUI,ComfyUI 不必开着。

## 提示词

- 这是通用模型,用**自然语言**,不用 Danbooru 标签、`@画师`、质量前缀、权重语法;括号照常写。
- 结构:用途/画风 → 场景 → 主体(角色名 + 作品 + 外观)→ 构图 → 光线/色彩 → 限制(`No text, no watermark`)。Codex 的 imagegen skill 也是这个顺序。
- **画幅只能写在提示词里**:写 `landscape 16:9 widescreen frame` → 实测 1672×941;写 `portrait orientation` → 实测 1024×1536。
- 不支持负面提示词,要避免的东西写成 `No ...` 句子。
- 安全:默认 safe;Codex 自身也有内容限制。

## 实测结论(2026-10-21)

- 芙宁娜(名字 + 外观描述):角色准确,服装细节完整;歌剧院舞台场景的纵深、光影和水滴效果是三个后端里最丰富的。
- 速度:竖图 98 秒、横图 49 秒(含 agent 开销)。
- 第一次测试时 Codex 沙箱里的 shell 命令报错(`setup refresh had errors`),所以脚本不依赖 Codex 自己复制文件,而是自己去 `generated_images` 取。
- 没测:参考图(`-i`)、多张(`count` > 1)、同一角色多次生成的一致性。
