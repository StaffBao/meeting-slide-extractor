# 环境与依赖参考（meeting-slide-extractor）

本文件记录运行流水线所需的环境、依赖、以及本工作流在沙箱/受限网络中
踩过的坑与对应的绕过办法。新机器上复现前请先通读本文件。

## 1. Python 运行时（受管 venv）

优先使用 WorkBuddy 受管 Python 或其隔离 venv，避免污染用户环境。
路径因机器而异（含用户名），**不要写死到脚本或文档中**，运行时获取：

```bash
python -c "import sys; print(sys.executable)"
```

将输出赋给变量 `PY`，后文命令统一用 `"$PY"` 调用。

创建/复用 venv 并安装依赖（仅装进受管目录）：

```bash
"$PY" -m venv "<你的venv目录>"     # 已存在则跳过
"$PY" -m pip install opencv-python-headless numpy pillow python-pptx \
    rapidocr-onnxruntime onnxruntime faster-whisper imageio-ffmpeg
```

> 说明：
> - `opencv-python-headless` 即可，无需 GUI。
> - `faster-whisper` 1.2.x 自带 ctranslate2 / onnxruntime，不依赖 PyTorch，体积小。
> - `rapidocr-onnxruntime` 首次运行会自动下载 OCR 模型到用户目录。

## 2. ffmpeg 位置

脚本已改为**运行时自动探测**，不再写死路径。探测顺序：

1. `imageio-ffmpeg` 自带二进制（受管 venv 内，推荐装 `imageio-ffmpeg`）
2. 系统 PATH 上的 `ffmpeg`
3. 环境变量 `MEETING_FFMPEG` 指向的可执行文件
4. 都找不到时报错并提示上述三种解决办法

`asr_transcribe.py` 与 `extract_keyframes.py` 均可省略 `--ffmpeg`；
如需覆盖，随时传 `--ffmpeg <路径>`。

## 3. 抽取全部关键帧（I-frame）

两种方式任选其一：

**(a) 直接用脚本**（推荐，输出 `kf_%010d.png`，文件名即帧 PTS）：

```bash
"$PY" extract_keyframes.py \
  --video "<会议.mp4>" \
  --images-dir images_tmp \
  --tmp-dir kf_all
```

**(b) 直接 ffmpeg 命令**：

```bash
"<ffmpeg>" -hide_banner -loglevel error -skip_frame nokey -i "<会议.mp4>" \
  -vsync vfr -frame_pts 1 -an kf_all/kf_%010d.png
```

产物 `kf_all/` 是后续聚类的输入。

## 4. ASR 首选模型与离线备选

首次使用先运行 `python scripts/asr_setup.py wizard`。选择和模型写入用户级
`MeetingSlideExtractor/config.json`；不会写入 Skill 文件夹。Windows 上 Key 写入当前用户的
环境变量，macOS/Linux 写入权限为 600 的用户配置文件。`status --json` 只返回是否已经配置，
永远不返回 Key 内容。

标准路径使用 `asr_qwen_chunks.py` 调用 `qwen-audio-3.0-asr-flash`。该模型列入百炼
Token Plan（个人版）的支持模型；实际额度、Credits 抵扣与限流以用户订阅和控制台为准。
本地文件先切成不超过 5 分钟的分片，转写后必须继续执行清理和抽样 QA。

以下 `faster-whisper medium` 说明是无法或不希望使用云端时的离线备选：

`asr_transcribe.py` 的当前实现是本地 `faster-whisper`，默认参数为
`--model medium`。这条路径不需要 ASR API Key。用户可以传 `--model-dir`
指向已下载的本地模型，以避免运行时联网。

**现象**：`faster-whisper` 默认从 HuggingFace 主站拉模型，沙箱环境对
`huggingface.co` 连接超时（ConnectTimeout），且 `huggingface_hub` 在清理
未完成临时文件时会触发 safe-delete 而中断。

**绕过办法**（两步）：

1. 设镜像环境变量，让 HF 客户端走可达镜像：

   ```bash
   export HF_ENDPOINT="https://hf-mirror.com"
   ```

2. 不用 `huggingface_hub`，改用 `curl` 直拉模型文件到本地目录，再由
   `asr_transcribe.py` 通过 `--model-dir` 加载本地路径：

   ```bash
   mkdir -p models/faster-whisper-medium && cd models/faster-whisper-medium
   BASE="https://hf-mirror.com/Systran/faster-whisper-medium/resolve/main"
   curl -fL -C - -o config.json  "$BASE/config.json"
   curl -fL -C - -o tokenizer.json "$BASE/tokenizer.json"
   curl -fL -C - -o vocabulary.txt "$BASE/vocabulary.txt"
   curl -fL -C - -o model.bin     "$BASE/model.bin"   # 约 1.5GB，可后台
   ```

   然后在转写时传 `--model-dir models/faster-whisper-medium`，不要传 `--model medium`。

> 镜像可用性因网络环境而异。若使用镜像，请先检查其可达性与信任要求。

### 云端 ASR 标准路径

对于本地文件，本 Skill 提供
`asr_qwen_chunks.py`：先按幻灯片边界把音频切成不超过 5 分钟的片段，再通过
DashScope 同步多模态生成端点调用 `qwen-audio-3.0-asr-flash`，合并为 `align_by_time.py` 可读取的时间戳文本。
API Key 只从 `DASHSCOPE_API_KEY` 环境变量读取，禁止写入脚本或命令参数。

`qwen-audio-3.0-asr-flash` 接受 URL/Base64，适合最长 5 分钟的本地分片。
本 Skill 为降低配置复杂度，不把要求公网/OSS 直链和单独异步流程的 FileTrans 纳入标准工作流。

- 官方模型说明：<https://help.aliyun.com/zh/model-studio/asr-model>
- 官方 API 参考：<https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference>
- 阿里云账号注册：<https://help.aliyun.com/zh/account/step-1-register-an-alibaba-cloud-account>
- API Key 创建：<https://help.aliyun.com/zh/model-studio/get-api-key>

## 5. 标点 / 段落化用的可选 LLM 接口

`punctuate_notes.py` 使用 OpenAI 兼容的文本 `chat/completions` 端点。这与 ASR 是两件事：

- 本地 faster-whisper ASR 不需要 API Key。
- 只有选择外部 LLM 加标点、分段，或对无时间戳逐字稿做内容映射时，才需要
  `--url`、`--api-key` 和 `--model`。
- 端点、模型可用性和费用会变化，不在共享版 Skill 中写死个人 Token Plan 地址或具体密钥。

> 安全提示：
> 1. API Key 属敏感信息，不要写死进脚本、文档或命令行参数。使用
>    `asr_setup.py wizard` 的隐藏输入、系统环境变量或受限权限的用户级凭证存储。
> 2. **严禁在脚本或文档中写死真实的个人绝对路径、用户名或机器专属 venv 目录**。
>    Python 用 `sys.executable` 运行时获取，ffmpeg 由脚本自动探测，路径一律使用占位符或自动解析。
>    分享/打包前搜索自己的实际用户名、个人项目目录名与 `sk-`，确认 0 命中。

## 6. 参数速查

| 脚本 | 关键参数 | 作用 |
|---|---|---|
| extract_keyframes.py | --video --images-dir --tmp-dir [--ffmpeg] | 抽 I-frame 到 kf_all/（ffmpeg 自动探测，可省） |
| extract_slides_iframes.py | --keyframes-dir kf_all --images-dir images --phash-thresh 10 --run-min-len 2 --border-thresh 10 --max-border 0.18 --filter-ui | 聚类+代表帧+去黑边+UI过滤→slides_meta.json |
| ocr_slides.py | --meta slides_meta.json --out slides_ocr.txt | 每页 OCR |
| asr_transcribe.py | --video --model-dir <本地> --out-srt --out-txt | 全程转写 |
| asr_setup.py | wizard / status --json / clear-key <provider> | 对话式选择 ASR，并以隐藏输入保存或删除用户级 API Key |
| asr_qwen_chunks.py | --chunks-dir --base-url --out-txt --out-json [--model] | 调用 qwen-audio-3.0-asr-flash 转写本地分片并记录耗时 |
| asr_openai_chunks.py | --chunks-dir --out-txt --out-json [--model] | 调用 OpenAI Audio Transcriptions API 转写本地分片并记录耗时 |
| clean_asr_transcript.py | --input --output [--replacements-json] | 保留时间戳，折叠相邻重复并应用可追踪的高置信词表修正 |
| align_by_time.py | --meta --asr asr_transcript.txt --ocr slides_ocr.txt --outdir output | 按时间戳对齐→生成 PPT、HTML 和按讲者分节的 Word 逐字稿 |
| punctuate_notes.py | --meta --url --api-key --model --outdir output | 加标点和分段→重建三件正式交付物 |

## 7. 已知限制

- `medium` int8 对医学/法规术语偶有同音错识（如「少点建设」→「哨点建设」），
  `punctuate_notes.py` 的 prompt 已内置常见纠错示例，仍可能遗漏，需人工校对。
- 录制开场 0–150s 暖场闲聊（识别噪声）按"最近前一页"规则并入第 1 页对应的讲稿字段，
  属正常上下文，未删除。
- `extract_slides_iframes.py` 的 UI 关键词过滤需 `rapidocr` 可用；若导入失败，
  `ocr_engine=None`，该过滤自动跳过（退化为仅亮度/对比度/去重过滤）。
