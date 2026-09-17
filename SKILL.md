---
name: meeting-slide-extractor
description: 从会议、培训、网课和屏幕录制视频中还原干净幻灯片，并用用户稿或 qwen-audio-3.0-asr-flash（离线时可用 faster-whisper）生成时间对齐、带标点和讲者分节的讲稿。默认交付纯幻灯片 slides.pptx、自包含可编辑 slides_viewer.html 和按讲者分节的 Word 逐字稿 transcript_by_speaker.docx。 Use for extracting clean slides and aligned transcripts from meeting or lecture videos; the default outputs are PPT, editable HTML, and a speaker-sectioned Word transcript. Do not generate a notes PPT unless explicitly requested.
metadata:
  version: "2.2.0"
---

# Meeting Slide Extractor

## Overview

将「共享屏幕 / 培训 / 会议录制」视频自动还原为干净的幻灯片合集，并生成
**全程逐字转写（带标点、分段落）**。当前版本始终以三件正式交付物为目标：
`slides.pptx`、`slides_viewer.html` 和 `transcript_by_speaker.docx`。核心解决两类问题：

> [!IMPORTANT]
> 只处理用户有权访问和转换的视频。启动处理前，必须提醒用户遵守原内容著作权、隐私与保密义务及来源平台服务条款，详见 `SOURCE_VIDEO_NOTICE.md`。若要调用外部 LLM，先明确告知相关文本将离开本地环境；有关 Skill 本身的准确性、兼容性与无保证条款，见 `DISCLAIMER.md`。

1. **幻灯片混杂过渡帧**（换页淡入淡出中间帧导致重影）—— 用 I-frame 感知哈希
   聚类 + 代表帧选择剔除。
2. **转写不完整 / 无标点** —— 首选用 `qwen-audio-3.0-asr-flash` 分片完成全程 ASR，
   再做清理和抽样 QA，并按视频时间戳对齐到每页幻灯片；无云端条件时使用本地 faster-whisper。

适用：PV/MAH 培训、学术讲座、产品发布、任意「演讲者共享 PPT」的录屏。

## 何时使用 / When to use

- 用户提供视频文件（mp4/mkv 等），要求「提取 PPT」「把视频转成幻灯片」或「整理会议讲稿」。 / The user provides a video and asks to extract slides or organize the meeting transcript.
- 用户已有转写，但需要补标点、分段、校对并对齐到幻灯片。 / The user already has a transcript that needs punctuation, paragraphing, correction, or slide alignment.
- 用户要求生成当前的三件标准交付物：纯幻灯片 `slides.pptx`、可编辑的 `slides_viewer.html` 和按讲者分节的 Word 逐字稿 `transcript_by_speaker.docx`。 / The user wants the standard PPT, editable HTML viewer, and speaker-sectioned Word transcript.
- **要求分节 / 分场次**：「按讲者分节」「自动加新增节」「这个培训有几位老师，帮我分开」
  「讲者的名字识别错了」→ 见 Step 7d（并顺带校正 PPT / HTML / 逐字稿里的姓名写法）。 / Use Step 7d for speaker/session sections and consistent speaker-name corrections across all three deliverables.
- **Mode A 触发语 / triggers**：「我导出了逐字稿，请和视频对齐并生成三件交付物」「这是文字稿，对应到每页」 / “I already have a transcript; align it to the video and generate the three deliverables.”
- **Mode B 触发语 / triggers**：「把培训视频的 PPT 摘出来」「提取会议共享屏幕的幻灯片」「给转写加标点」 / “Extract the slides and transcribe this meeting video.”

## 两种模式（先选模式，再跑流水线）

| 模式 | 输入 | 文字来源 | 典型场景 |
|---|---|---|---|
| **Mode A（用户给逐字稿）** | 视频（取幻灯片）+ 用户提供的文字稿文件 | 用户稿（LLM 加标点、按页对应） | 腾讯会议已导出 AI 转写，或用户手头有整理好的稿 |
| **Mode B（视频 ASR）** | 仅视频 | 首选 qwen-audio-3.0-asr-flash 分片识别；faster-whisper 为离线备选 | 没有现成转写，需要从头识别 |

- Mode A 的逐字稿**自动识别是否带时间标记**：
  - 带时间（`[HH:MM:SS,mmm]` / `[HH:MM:SS]` / `[MM:SS]` / `HH:MM:SS` 等）→ 按视频时间精确对应到当时放映的页。
  - 不带时间（纯文字）→ 用 LLM 按每页幻灯片 OCR 内容把整段文字拆成段落并对应到各页；若无 LLM 通道则回退「按页序均分」。
- 两种模式最终都产出三件正式交付物：**`slides.pptx` + `slides_viewer.html` + `transcript_by_speaker.docx`**。PPT 不含讲稿；幻灯片与逐字稿的按页对照位于 HTML，完整逐字稿另以 Word 交付。 / Both modes produce the same three deliverables: a slides-only PPT, an editable HTML slide/transcript viewer, and a speaker-sectioned Word transcript.

### Mode A 流水线

```bash
PY="<你本机的 Python 解释器路径（装好依赖后，运行 python -c \"import sys; print(sys.executable)\" 获取）>"

# Step A1 — 抽取关键帧 → Step A2 聚类/去黑边/过滤 见上文 Step 1–2
# Step A3 — 每页 OCR 见上文 Step 3（产出 slides_ocr.txt，供无时间戳时做内容对应）

# Step A4 — 读入用户逐字稿，整合成段落并对应到每页
"$PY" scripts/ingest_user_transcript.py \
  --meta slides_meta.json \
  --transcript "<用户逐字稿.txt>" \
  --ocr output/slides_ocr.txt --outdir output \
  --mode auto \
  --url "<OpenAI-compatible chat-completions endpoint>" \
  --api-key "<API key>" \
  --model "<text model>"
```

- 带时间戳的稿：直接时间对齐，无需 LLM（可省略 `--url/--api-key`）。
- 不带时间戳的稿：LLM 把文字拆段并映射到页；无 LLM 时自动按页序均分（质量较低，仅兜底）。
- 产物：`slides_meta.json` 写入 `notes` + 纯幻灯片 `slides.pptx` + `slides_viewer.html`（默认单文件）
  + Word 逐字稿 `transcript_by_speaker.docx`（+ 自查对照 `transcript_from_slides.md`）。
- 如需再润色标点，可继续跑 `punctuate_notes.py`（见 Mode B Step 6）。

### Mode B 流水线

见下方 Step 1–6（ASR 全程识别 → 时间对齐 → LLM 加标点分段落），
若需要按讲者分节，则继续 Step 7d（生成 `sections.json`），然后重建三件正式交付物。

## 前置：环境准备（必读）

依赖安装、ffmpeg 位置、本地 faster-whisper 模型下载、可选文本 LLM 接口与参数速查，
**全部写在 `references/env.md`**。新机器复现前先读它。

### 首次运行 ASR 配置协议

在任何云端 ASR 调用或大模型下载之前，先运行：

```bash
"$PY" scripts/asr_setup.py status --json
```

- `ready=true`：遵循已保存的 `mode` 与 `provider`，不要重复询问，也不要显示或打印 Key。
- 未配置：在聊天框只询问一个问题：“请选择转写方式：云端 ASR（推荐，可能产生少量费用）或离线 ASR（首次需下载约 1.53 GB 模型文件，耗时较长）？”
- 用户选择云端且尚未指定服务商时，再问：“千问 Token Plan（推荐）或 OpenAI API？”
- 不要求用户把 API Key 粘贴进聊天。优先打开可见终端或给出
  `python scripts/asr_setup.py wizard`，让用户在本地隐藏输入中配置。
- 用户明确要求重新配置时，重新运行向导；用户要求删除凭证时运行
  `python scripts/asr_setup.py clear-key qwen` 或 `... clear-key openai`。
- 用户选择离线后立即保存 `offline`，不要再追问 API Key。
- 将音视频发送到任何云端 ASR 前，明确说明音频会离开本机；用户的云端选择即授权本次上传，不授权其他外部用途。

**ASR 路由**：千问使用 `asr_qwen_chunks.py` 与 `qwen-audio-3.0-asr-flash`；OpenAI 使用 `asr_openai_chunks.py` 与 `gpt-4o-mini-transcribe`；离线使用 `asr_transcribe.py` 与 `faster-whisper medium`。Codex 登录凭证不得当作 OpenAI API Key。标准流程不使用要求公网/OSS 直链的 FileTrans。

## 流水线（按顺序执行）

工作目录建议新建一个项目文件夹，下列脚本均从 `scripts/` 复制过来运行。

### Step 1 — 抽取全部关键帧（I-frame）

```bash
PY="<你本机的 Python 解释器路径（装好依赖后，运行 python -c \"import sys; print(sys.executable)\" 获取）>"
"$PY" scripts/extract_keyframes.py \
  --video "<会议.mp4>" \
  --images-dir images_tmp \
  --tmp-dir kf_all
```

- `--ffmpeg` 可省略：脚本会自动探测（imageio-ffmpeg 自带二进制 → 系统 PATH →
  `MEETING_FFMPEG` 环境变量），找不到时会给出明确提示；也可显式传 `--ffmpeg <路径>`。

产物：`kf_all/kf_%010d.png`（文件名即帧 PTS，供后续时间戳计算）。

### Step 2 — 聚类、选代表帧、去黑边、过滤噪声

```bash
"$PY" scripts/extract_slides_iframes.py \
  --keyframes-dir kf_all --images-dir images \
  --video "<会议.mp4>" \
  --phash-thresh 10 --run-min-len 2 \
  --border-thresh 10 --max-border 0.18 --filter-ui \
  --review-dir review
```

- `run-min-len 2`：单帧 run（淡入淡出/闪帧/瞬时 UI）视为过渡，进 `review/`。
- 代表帧取「与该 run 多数哈希 Hamming 距离最近」的帧，避免取到过渡边缘帧。
- `crop_black_borders`：逐行/列均值亮度扫描，裁近黑边框（每边 ≤18%）。
- `--filter-ui`：对代表帧做 RapidOCR，命中 ≥2 个 UI 关键词才拒绝（WPS 编辑视图、
  腾讯会议主页、播放器窗口、桌面等）。
- 产物：`images/slide_NNN.png` + `slides_meta.json`（每页含 `t`=视频秒数）
  + `review/rejected_meta.json`。

### Step 3 — 每页 OCR

```bash
"$PY" scripts/ocr_slides.py --meta slides_meta.json --out output/slides_ocr.txt
```

产物：`output/slides_ocr.txt`（每页一节，`# 第 N 页` 分隔）。

### Step 4 — 全程 ASR 转写

**云端路径**：先用 ffmpeg 按幻灯片边界或每 5 分钟以内切出音频，文件命名为
`chunk_START_END.mp3`（START/END 是整秒），再根据已保存的 provider 选择脚本。

千问 Token Plan：

```bash
"$PY" scripts/asr_qwen_chunks.py \
  --chunks-dir output/asr_chunks \
  --base-url "https://dashscope.aliyuncs.com/compatible-mode/v1" \
  --out-txt output/asr_transcript.txt \
  --out-json output/asr_timing.json
```

- 运行前设置 `DASHSCOPE_API_KEY`；禁止把 Key 写入脚本、README 或产物。
- 产物：`output/asr_transcript.txt`（格式 `[HH:MM:SS,mmm] 文本`）。
- 不自动使用 `qwen-audio-3.0-asr-flash-filetrans`；它要求公网/OSS 文件直链并使用另一套异步流程。

OpenAI API：

```bash
"$PY" scripts/asr_openai_chunks.py \
  --chunks-dir output/asr_chunks \
  --out-txt output/asr_transcript.txt \
  --out-json output/asr_timing.json
```

- 需要独立的 `OPENAI_API_KEY`；Codex 订阅或登录不会自动提供该凭证。
- **离线备选**：按 `references/env.md` 第 4 节准备 `faster-whisper-medium`，再运行
  `asr_transcribe.py --video <会议.mp4> --model-dir models/faster-whisper-medium --out-srt output/asr_transcript.srt --out-txt output/asr_transcript.txt`。

#### Step 4b — 标准清理与质量门槛

ASR 原始识别结果是机器转写底稿，不应直接宣称为人工校订稿。标准流程必须同时保留原稿与清理稿：

```bash
"$PY" scripts/clean_asr_transcript.py \
  --input output/asr_transcript.txt \
  --output output/asr_transcript_clean.txt \
  --replacements-json output/asr_replacements.json
```

- `asr_transcript.txt` 永久保留，不覆盖，便于追溯模型原始结果。
- `asr_replacements.json` 只写从画面、课程资料、讲者自报姓名或人工抽听中确认的高置信修正；不得为了让文字更顺而改写原意。
- 自动折叠相邻长句重复并规范异常重复标点；不删除口头禅、重复表达或不流畅句，因为逐字稿应保留实际发言。
- 用清理稿进入 Step 5。至少抽听开头、中段、结尾各 60 秒，并复核人名、机构、书名、专业术语和数字；发现系统性错词时补入 replacement map 后重建三件交付物。
- 自动 ASR 未经全程人工复核时，交付说明应写“自动转写并抽样校对”，不能写“已完整人工校订”。视频在截取点中断时，逐字稿末句可能不完整，应明确标注测试范围。

### Step 5 — 按时间戳对齐到幻灯片

```bash
"$PY" scripts/align_by_time.py \
  --meta slides_meta.json \
  --asr output/asr_transcript_clean.txt \
  --ocr output/slides_ocr.txt \
  --outdir output
```

- 每页幻灯片有 `t`（视频秒数）；每段 ASR 有绝对开始时间。把每段分配给
  「当时屏幕上显示的页」（`bisect` 取最大 `t ≤ 段时刻`）。比词汇重叠匹配可靠得多。
- 更新 `slides_meta.json` 的 `notes` 字段，并重建：
  `output/slides.pptx`（纯幻灯片，传给 `--sections` 时含【新增节】分页）、
  `output/slides_viewer.html`（幻灯片 + 演讲稿镶嵌）、
  `output/transcript_by_speaker.docx`（Word 逐字稿，按讲者分节）。

### Step 6 — 加标点、整理段落（用 LLM）

```bash
"$PY" scripts/punctuate_notes.py \
  --meta slides_meta.json --ocr output/slides_ocr.txt --outdir output \
  --url "<OpenAI-compatible chat-completions endpoint>" \
  --api-key "<API key>" \
  --model "<text model>"
```

- 逐页把原始讲稿送 LLM：加中文标点、合并自然句、修正明显同音错字、长文酌情分段。
- 重建纯幻灯片 `slides.pptx` + `slides_viewer.html` + Word 逐字稿 `transcript_by_speaker.docx`
  （另生成旧式逐页稿 `output/transcript.txt`）。
  （按页时间窗整理的带标点分段落稿，每段标注 `（mm:ss）`）。
- 密钥务必从命令行传入，不要写死进脚本。

### Step 7 — 生成 HTML viewer（三件正式交付物之一）

流水线（Step 5/6 与 Mode A）在重建时**默认**调用 `build_notes_ppt.build_html`，
产出 `output/slides_viewer.html`：**每页左侧为幻灯片“舞台”，右侧为「演讲稿」（左右对照）**；
演讲稿区**自带独立上下滚动轨道**，讲稿很长时在卡片内滚动，不撑高页面。
V2.2.0 起页面还带：

- **左侧缩略图轨道**（页面总览）：按「节」分组，点缩略图/节标题直接跳页，滚动时自动高亮
  并跟随；**默认展开、可折叠**，折叠状态按 deck 记忆。
- **页码跳转输入框**：顶栏输入页码 + 「跳转」（回车亦可），越界会提示。
- **分节条**：每节首页之前有一条「新增节」分隔条；串场句所在的页里，还会在**段落中间**
  插一行 `下一节 · …` 提示（见 Step 7d）。
- **「编辑 / 退出编辑」**（V2.2.0 由「校对模式」改名）：见 Step 7c。

也可单独重建：

```bash
"$PY" scripts/build_notes_ppt.py --meta slides_meta.json \
  --ocr output/slides_ocr.txt --outdir output --title "幻灯片与讲稿" \
  [--sections output/sections.json] [--no-rail] \
  [--separate-images] [--max-width 1500] [--quality 80]
```

> 早期版本的 `--notes-pptx` 仅作兼容选项保留，不属于当前标准流程，不应默认调用。

**关于幻灯片图片**：viewer 需要显示幻灯片，因此图片是**必需**内容。两种供给方式：
- **默认（推荐）：把幻灯片压成 JPEG 后以 base64 内联进 HTML，产出**单个自包含
  `.html`**——磁盘上不再有 `slides/` 文件夹，转发/复制单个文件即可完整打开，
  不会因为漏拷 `slides/` 而丢图。代价是单文件体积明显变大（截图越大越明显，可用
  `--max-width` / `--quality` 控制；左侧缩略图另有专用小图，约再增 7%）。**
- `--separate-images`：图片压成 JPEG 存到 `output/slides/slide_NNN.jpg`，由 HTML
  相对引用（HTML 体积小，但**必须连同 `slides/` 目录一起分享**，否则图片全丢）。

### Step 7b — 旧版兼容入口：由带备注 PPT 生成 viewer（非标准流程）

若手上已有带备注的 PPT（本 skill 早期版本产出，或他人提供），无需重跑视频流水线：

```bash
# 默认：单文件，图片 base64 内联，仅产出 slides_viewer.html（无 slides/ 目录，便于整体分享）
"$PY" scripts/build_html_from_pptx.py \
  --pptx output/slides_with_notes.pptx --outdir output --title "幻灯片与讲稿"

# 可选：图片落盘到 <outdir>/slides/，HTML 相对引用（HTML 更小，但需连目录一起分享）
"$PY" scripts/build_html_from_pptx.py \
  --pptx output/slides_with_notes.pptx --outdir output --title "幻灯片与讲稿" \
  --separate-images --max-width 1500 --quality 80
```
产出 `<outdir>/slides_viewer.html`（默认是单文件；加 `--separate-images` 时另有
`<outdir>/slides/slide_NNN.jpg`）。

### Step 7c — 页内编辑（V2.1.1 起）：改完直接写回 HTML

生成的 `slides_viewer.html` **自带一个页内编辑器**，用于修 ASR 同音错字（如
「少点建设」→「哨点建设」），无需回到命令行：

1. 页面右上角点 **「编辑」** → 每页右侧「演讲稿」面板变成一个可直接输入的文本框
   （保持原有固定高度与内部滚动，版式不变）；V2.2.0 起**每节的标题也变成输入框**，
   可以改节名（例如把自动生成的题目改成自己习惯的叫法）。
2. 改完点 **「保存（覆盖原文件）」** 或 **「另存为…」**，把改正后的内容写回 HTML。

**保存机制与限制（重要）**：

| 按钮 | 行为 | 前提 |
|---|---|---|
| 另存为… | 弹系统保存框 → 写盘 | Chromium 内核（Chrome/Edge）且**页面是顶层窗口** |
| 保存（覆盖原文件） | 复用本次会话记住的文件句柄，一键覆盖，不再弹框 | 同上（首次点会先弹一次保存框） |
| 自动回退 | 两个按钮都改为**下载新文件** | 非 Chromium，或页面在 iframe 内（含各种预览面板） |

- **必须用浏览器直接打开本文件**（双击 / 拖进 Chrome），**不要在嵌入的预览窗口里改**——
  预览窗口是 iframe，浏览器的文件写盘接口在跨源 iframe 内不可用，此时会退化成下载。
  页面右上角的**环境徽标会实时显示**当前是可「保存」还是只能「下载」。
- 出于浏览器安全策略，网页**无法知道原文件路径**，所以「保存」的第一次等于「另存为」
  （需你选一次文件）；浏览器重启后需重新选一次，同一次会话内之后都是一键覆盖。
- **草稿保护**：编辑过程中的改动（讲稿 + 节标题）会自动暂存到浏览器本地；误关页面后再打开，
  顶部会出现黄色提示条可一键恢复。页面有未保存改动时关闭会弹确认框。
- 其他按钮：「还原全部」恢复为最初内容（已写盘的修改不受影响）、每页「已改」小标签可
  单独还原该页、「复制全部讲稿」按 `## 第 N 页` 复制到剪贴板（V2.2.0 起同时带上
  `# 【新增节 N】…` 行）。
- 输出的 HTML **仍带编辑器**，可反复迭代；结构上仍是单文件自包含。
- 编辑期间 `.notes` 面板被替换成 textarea，因此**段中「下一节」提示在编辑态会临时隐藏**，
  退出编辑即恢复。

### Step 7d — 分节：识别讲者、生成【新增节】、校正姓名（V2.2.0 新增）

```bash
"$PY" scripts/build_sections.py \
  --meta slides_meta.json --asr output/asr_transcript.txt \
  --ocr output/slides_ocr.txt \
  --out output/sections.json --log output/sections_log.md \
  --deck-title "<培训名称>" [--fix-meta] [--override <人工指定.json>]
```

**为什么不用声纹分离（diarization）**：声纹方案依赖重（约 2GB 依赖、CPU 上数小时），
而培训录像里有两个既便宜又极稳定的文本信号：

1. **主持人串场句式**：`有请 X 老师` / `谢谢 X 老师`（在本 skill 的参考录像里 3h44m
   只有 8 句候选，去重后 7 条边界）；
2. **讲者自己的题目页**：用幻灯片 OCR 读「汇报人：X」或姓名徽章，取到**题目 + 姓名**。

**判定规则（都是从实测踩坑里定下来的）**：

- 串场句**必须点到具体人名**才算边界。泛泛的「谢谢大家 / 感谢各位」是讲者自己的话，
  不是边界（参考录像里 1:45:24 就有一处，若不过滤会多切一节）。
- 同一句串场可能因试音/重说出现两次 → **去重**：保留「该页讲稿里确实出现此姓名」的那条。
- 时间戳映射到页会落在**上一页**（主持人先说话、讲者随后才翻页）→ 因此要**向前**搜索
  讲者的题目页（实测 26→27、93→94）。
- **姓名以幻灯片为准**：ASR 会听错（实测「史兰」应为「史岚」、「蒲一虎」应为「浦义虎」）。
  脚本会输出 `name_fixes` 并把 `--fix-meta` 应用到 `slides_meta.json` 的讲稿正文，
  使 **PPT / HTML / 逐字稿三处写法完全一致**。
- `kind`：`opening`（开班动员/致辞，串场句常只报机构名，题目回退为「开班动员」）、
  `talk`；如后续出现问答/点评，可用 `--override` 指定 `qa` / `panel`（标题分别为
  「问答」「专家点评」）。
- 题名回退顺序：题目页上的 `《…》` 行 → 最长可行文本行（并把被 OCR 拆成两行的长题目
  重新拼回，如 p94「创新药出海的药物警戒体系构建」+「与全球合规实践」）。
- **分隔条位置**：每节首页前有一条「新增节」分隔条；另外把串场句**定位到它在上一页讲稿里的
  字符偏移**，在**该句结束之后（段落中间）**再插一行 `下一节 · …`，这样「谁在串场、
  哪段属于下一节」一目了然。定位用最长公共子串（讲稿已被 LLM 加过标点，无法逐字匹配）。

产出：`output/sections.json`（含 `sections` / `speakers` / `name_fixes`）、
`output/sections_log.md`（检测过程与每步依据，便于复核）。随后把 `--sections` 传给
`align_by_time.py` / `punctuate_notes.py` / `build_notes_ppt.py`，
由 `build_clean_pptx(..., sections=...)` 生成**带【新增节】分页的纯幻灯片 PPTX**
（同时写 PowerPoint 原生「节」，此步失败不影响成品，仅少一个节窗格分组）。

## 输出文件

### 三件正式交付物 / Three standard deliverables

| 文件 | 说明 |
|---|---|
| `output/slides.pptx` | 纯幻灯片 PPT，不含讲稿；可带分节页与 PowerPoint 原生节。 / Slides-only PPT with optional divider slides and native PowerPoint sections. |
| `output/slides_viewer.html` | 自包含、可编辑的幻灯片＋讲稿查看器。 / Self-contained, editable slide-and-transcript viewer. |
| `output/transcript_by_speaker.docx` | 带讲者一览表、分节标题、时间/页码范围和连续发言正文的 Word 逐字稿；不混入幻灯片 OCR。正文中文使用宋体 12 磅，英文使用 Arial Unicode MS 12 磅。 / Formatted Word transcript with a speaker overview, section headings, ranges, and continuous speech text; slide OCR is excluded. Body text uses 12 pt SimSun for Chinese and 12 pt Arial Unicode MS for English. |

> 默认只向用户交付上述三件。下列内容是流水线中间文件、诊断文件或显式选择的兼容产物。 / Deliver only the three files above by default; the files below are intermediate, diagnostic, or explicit compatibility outputs.

### 中间、诊断与兼容文件

| 文件 | 说明 |
|---|---|
| `images/slide_NNN.png` | 裁剪后干净幻灯片 |
| `slides_meta.json` | 每页元数据（n / file / t / notes）。V2.2.0 起 `build_sections.py --fix-meta` 会把讲者姓名的 ASR 错拼就地改成幻灯片写法 |
| `output/slides_ocr.txt` | 每页 OCR 文字 |
| `output/asr_transcript.txt` / `.srt` | 全程逐字转写（无标点 / 带时间戳） |
| `output/sections.json` | **V2.2.0 新增**：分节结果（`sections` 每节的 `kind/speaker/topic/title/from_n/to_n/from_t/to_t/anchor`、`speakers`、`name_fixes`） |
| `output/sections_log.md` | **V2.2.0 新增**：分节检测过程日志（候选串场句、去重、题目页评分、姓名校正），便于复核 |
| `output/transcript_from_slides.md` | 流水线**自查对照**用：每页 OCR 与对应讲稿并排，供人工核对「画面上的文字」与「说出来的话」是否对得上。**不是交付物** |
| `output/transcript.txt` | 旧形式的逐页带标点稿（每段前缀 `（mm:ss）`），保留备用 |
| `output/slides_with_notes.pptx` | 旧版兼容产物；仅在明确传入 `--notes-pptx` 时生成，不属于标准交付。 |
| `output/slides/slide_NNN.jpg` | 幻灯片缩图。**仅当加 `--separate-images` 时才落盘**并由 HTML 相对引用（此时必须连目录一起分享）；默认改为 base64 内联、无此目录 |
| `review/` | 被拒过渡帧 / 噪声帧，供人工复核 |

HTML 生成入口为 `build_notes_ppt.build_html`；`align_by_time.py`、`punctuate_notes.py`
和 Mode A 的 `ingest_user_transcript.py` 默认都会调用它。默认 `inline_images=True`，
因此 HTML 是单文件；只有显式使用 `--separate-images` 时才会落盘图片目录。

## 变更记录

> 以下仅记录历史版本的行为；其中的旧文件名、旧布局和旧按钮名称不代表当前默认输出。

### V2.2.0
- **新增分节（Step 7d）**：新增 `scripts/build_sections.py`，从「主持人串场句式 + 讲者题目页」
  自动判定讲者切换，产出 `sections.json` / `sections_log.md`，并让 **PPTX / HTML / 逐字稿
  三处带同一套【新增节】标记**。**不用声纹分离**（依赖重、CPU 上数小时），改用文本信号。
- **讲者姓名以幻灯片为准**：ASR 听错的名字（实测「史兰」→「史岚」、「蒲一虎」→「浦义虎」）
  会被识别并输出 `name_fixes`；`--fix-meta` 就地改 `slides_meta.json`，`build_html` 用同一
  映射校正锚点串，**保证三份交付物姓名完全一致**。
- **分隔条可落在段落中间**：用最长公共子串把串场句定位到上一页讲稿的**字符偏移**，在
  「串场句结束之后」插入 `下一节 · …` 提示（讲稿已被 LLM 加过标点，无法逐字匹配）；
  每节首页前另有一条「新增节」分隔条。实测落点：第 3 / 26 / 93 页（正文段落之间）。
- **左侧缩略图轨道**：按节分组、可点击跳页、随滚动自动高亮与跟随；**默认展开、可折叠**，
  折叠状态按 deck 记忆。缩略图用**专用小图**（默认 260px / q58）内联，单文件体积约 +7%。
- **页码跳转输入框**：顶栏输入页码 + 「跳转」，支持回车，越界会提示；顺带修掉「焦点在
  输入框/textarea 时方向键会误翻页」的老问题。
- **按钮改名与节标题可编辑**：「校对模式 / 退出校对」→ **「编辑 / 退出编辑」**；
  节标题在编辑态变成输入框，可改节名，与讲稿一并纳入「已改动」计数、草稿暂存、
  导出写回与「还原全部」。
- **PPT 也新增节**：`build_clean_pptx(..., sections=...)` 在每节首页前插入一页
  【新增节】分隔页（节名 + 页码区间 + 时间区间，带强调色色带），并写入 PowerPoint
  **原生 `p14:sectionLst`**（节窗格可直接看到）。原生节写入是**非破坏性**的：先写临时文件、
  重新打开校验通过后才替换目标文件，任何异常都保留已生成的可见分隔页版本。
- **收窄交付集（按用户澄清）**：PPT 只出 **`slides.pptx`（只有幻灯片、不含讲稿）**，
  讲稿归 HTML；带备注的 `slides_with_notes.pptx` **不再默认产出**（`--notes-pptx` 才生成）。
  - 为此把 `build_clean_pptx(meta, out_path, sections=None)` 扩成**支持分节**：每节首页前插
    【新增节】分隔页 + 写 PowerPoint 原生节；`--pptx` 参数改名为 `--notes-pptx`（legacy opt-in）。
  - **交付物一律不含任何备注**：连分节页也不再写 notes（原先写了一句「【新增节】…」，已去掉）。
  - 顺带修一个自查误判：原生节的命名空间前缀由 lxml 自动生成为 `ns0:`（XML 合法、PowerPoint 可识别），
    现显式 `etree.register_namespace("p14", …)` 输出规范前缀；**并且校验改为按 `<p14:section name="…">`
    实读节名**——只验 URI 会给出假阳性确认（这次就踩了）。
- **逐字稿改为「纯 ASR 正文 + 按讲者分类」（按用户澄清）**：最初新增 `build_transcript()`
  产出 Markdown；当前正式交付已升级为 `build_transcript_docx()` 生成
  `output/transcript_by_speaker.docx`——开头「讲者一览」表，之后每节一段连续正文；
  **不含幻灯片 OCR、不做逐页切分**。原来那份 `transcript_from_slides.md`（每页 OCR 与讲稿并排）
  降级为**流水线自查对照**用途，不再当交付物。
- **时间格式修正**：超过 1 小时的录像时间由 `158:34` 改为 `2:38:34`；末节未知结束时间
  显示为「`2:38:34 起`」而非 `00:00`。
- 校验方式：10 个脚本 `py_compile` 全通过；生成页抽出的 2 个 `<script>` 块 `node --check`
  通过；**jsdom 77 项 DOM 行为断言全部通过**（缩略图/页码跳转、折叠记忆、编辑计数、
  节标题编辑、草稿落盘、导出串体检、导出→重开往返、键盘守卫、分节内容正确性）；
  对 124 页真实录像核对：4 节边界、4 个节名、段中提示页（3/26/93）、三份文件姓名一致。

### V2.1.1
- **新增页内校对模式（Step 7c）**：HTML 右上角加「校对模式」开关，打开后每页「演讲稿」
  面板变为可直接输入的文本框（沿用原有固定高度与内部滚动轨道，版式不变）；
  改完点「保存（覆盖原文件）」或「另存为…」把讲稿写回 HTML。用于修 ASR 同音错字。
- **写盘机制**：`showSaveFilePicker` 选路径 + `FileSystemFileHandle.createWritable()` 写盘；
  「保存」复用会话内的文件句柄实现一键覆盖（浏览器无法得知原文件路径，故首次等同于另存为）。
  **环境不支持时（非 Chromium、或页面在 iframe 预览窗口内）自动退化为下载新文件**，
  并在右上角用徽标实时提示当前处于哪种模式。
- **草稿保护**：编辑内容防抖 600ms 自动暂存到浏览器本地存储（key 用 `标题+页数+文件名`
  的 MD5 加盐，避免同一浏览器下不同 deck 互相覆盖）；重开页面顶部出现恢复条；
  有未保存改动时关闭页面弹确认框。
- **其他**：整页「还原全部」、每页「已改」标签可单独还原该页、「复制全部讲稿」按
  `## 第 N 页` 复制到剪贴板；导出时自动清理编辑态标记（`editing` 类、高亮页、页码），
  导出的 HTML 仍保留校对能力。
- 新增 `_norm_notes()` 统一把讲稿的 CRLF/CR 归一为 LF，供段落渲染与页内编辑共用同一份文本，
  并把它写入 `section[data-notes]` 作为编辑初值（已验证 124 页 `data-notes` 与 `<p>` 段落数完全一致）。
- 校验方式：`py_compile` 全通过；生成页抽出的两个 `<script>` 块 `node --check` 通过；
  用 jsdom 跑 34 项 DOM 行为断言（进入/退出校对、改字计数、单页与全部还原、草稿落盘、
  导出串结构、以及「导出→重新打开」往返）全部通过。

### V2.1
- **布局改版**：viewer 由“上幻灯片 / 下演讲稿”改为**左幻灯片、右演讲稿**（左右对照阅读）；
  演讲稿面板加**独立上下滚动轨道**，长讲稿在卡片内滚动而不撑高页面。
- **默认改为单文件自包含：** `build_html(..., inline_images=True)` 成为**默认值**，幻灯片图片以
  **base64 内联**进 HTML，产出**单个自包含 `.html`**（磁盘上不再需要 `slides/` 目录），
  转发/复制单个文件即可完整打开，不会因漏拷 `slides/` 而丢图——这是分享场景下最不易出错的形式。
  如需旧的“图片落盘 + 相对引用”形式（HTML 更小），改用 `--separate-images`
  （`build_notes_ppt.py` / `build_html_from_pptx.py` / `align_by_time.py` / `punctuate_notes.py` 均支持）。
- 明确：幻灯片图片是 viewer 的**必需**内容——默认内联为单文件，或加 `--separate-images` 落盘 `slides/`。

### V2.0
- **交付形式变更**：`slides_with_notes.pptx` + `slides_with_text.pptx` → **单个
  `slides_viewer.html`**（PPT 界面式：每页上方为幻灯片“舞台”，下方为「演讲稿」面板；
  支持上一页/下一页与方向键翻页、滚动高亮当前页）。
- 新增 `build_notes_ppt.build_html()`；新增 `scripts/build_html_from_pptx.py`
  （把已有带备注的 PPT 直接转成 viewer，无需重跑视频流水线）。
- 保留 `slides.pptx` 干净版；原 `build_notes_pptx` / `build_text_pptx` 函数保留但
  不再默认调用。

### V1.x
- 三版 PPT（干净版 / 图+备注 / 图+右侧文字）+ Markdown + 逐字稿。

## 已知限制

- ASR 对医学/法规术语偶有同音错识（如「少点建设」→「哨点建设」），`punctuate_notes.py`
  的 prompt 已内置纠错示例，仍可能遗漏，需人工校对。
- 录制开场暖场噪声按「最近前一页」并入第 1 页备注，属正常上下文。
- UI 关键词过滤依赖 RapidOCR；若其不可用则该过滤自动跳过。
- **页内编辑的写盘能力受浏览器限制**：只有 Chromium 内核（Chrome / Edge）且页面为顶层窗口时
  才能「保存 / 另存为」直接写盘；Firefox / Safari 或在 iframe（各种预览面板）内打开时，
  按钮会自动退化为下载新文件——功能不丢，但需要手动替换原文件。页面徽标会提示当前模式。
- 页内编辑只能改「讲稿正文」和「节标题」；改不了幻灯片图片、页码或时间戳（那些来自视频
  流水线，需要重跑 pipeline）。编辑结果也不回写 `slides_meta.json`——如需让修正同时进入
  Word / PPT 版本，请用「复制全部讲稿」导出后在命令行重跑构建。
- **分节依赖串场句式，不是万能的**：若主持人不报姓名（「下面请下一位」）、或讲者干脆
  没有题目页，该处就切不出节。此时用 `--override` 传人工分节定义：
  `{"sections":[{"kind":"talk","speaker":"张三","from_n":40,"topic":"…"}]}`。
- 串场句与题目页都依赖 ASR 与 OCR 质量；题目页若被 OCR 读成大段乱码，题目会退回
  「讲者名」（无书名号），可在 HTML 编辑态直接改节标题。
- 段中「下一节」提示在**进入编辑态时会临时隐藏**（讲稿面板整体变成 textarea），
  退出编辑即恢复；提示只是阅读线索，不参与导出文本。
- PowerPoint **原生节**（节窗格）由手写 XML 写入，非 python-pptx 官方 API；脚本已做
  临时文件 + 重开校验 + 失败回退，最坏情况是少了节窗格分组，**可见的【新增节】分隔页一定在**。
  加了分隔页后 PPT 页数 = 幻灯片数 + 节数，与 HTML 的「第 N 页」（录像页码）不再一一对应。
- 左侧缩略图轨道使单文件体积约 +7%；如不需要可加 `--no-rail` 关闭。

## 参考

- `references/env.md` — 依赖、ffmpeg、模型下载绕过、LLM 通道、参数速查。
- `README.md` — 中英文安装、分享与交付物概览。
- `SOURCE_VIDEO_NOTICE.md` — 输入视频的合法来源、内容权利、隐私和平台条款声明。
- `DISCLAIMER.md` — Skill 本身的准确性、兼容性、第三方服务和无保证条款。
- `LICENSE` — 本 Skill 代码与文档的 MIT 许可证（Copyright 2026 Staffbao）。
- `requirements.txt` — 可分享的 Python 运行依赖清单。
- `scripts/` — 可独立运行的 Python 脚本：`extract_keyframes.py`、
  `extract_slides_iframes.py`、`ocr_slides.py`、`asr_transcribe.py`、
  `align_by_time.py`（Mode B 时间对齐）、`asr_setup.py`（用户级 ASR 配置与隐藏 Key 输入）、`asr_qwen_chunks.py`（本地音频分片调用 qwen-audio-3.0-asr-flash）、`asr_openai_chunks.py`（分片调用 OpenAI 转写接口）、`clean_asr_transcript.py`（保守折叠重复片段并应用可追踪的专名校正）、`punctuate_notes.py`（Mode B 加标点）、
  `ingest_user_transcript.py`（Mode A 用户逐字稿）、`build_sections.py`
  （**V2.2.0：分节检测 + 讲者姓名校正**）、`build_notes_ppt.py`（共享构建库，
  含 `build_html`（V2.x viewer / V2.1.1 页内编辑 / V2.2.0 缩略图轨道与分节）、
  `build_markdown`、`build_clean_pptx`（V2.2.0 纯幻灯片 + 分节页）、
  `build_notes_pptx`（legacy，仅 `--notes-pptx` 时调用））、`build_html_from_pptx.py`
  （V2.x：由已有带备注 PPT 直接生成 viewer）。

