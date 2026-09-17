# Meeting Slide Extractor / 会议视频转幻灯片

[简体中文](#简体中文) · [English](#english)

> [!IMPORTANT]
> 本工具仅应用于你有权处理的视频。使用者必须拥有来源视频的合法访问权，并遵守原内容的著作权、隐私要求及来源平台服务条款。详见 [视频来源与内容权利声明](SOURCE_VIDEO_NOTICE.md)。
>
> Use this tool only with videos you are authorized to process. You must have legitimate access to the source video and comply with applicable copyright, privacy, and platform terms. See the [Source Video and Content Rights Notice](SOURCE_VIDEO_NOTICE.md).

## 简体中文

Meeting Slide Extractor 是一个 Codex Skill，用于从会议、培训、网课和屏幕录像中提取干净幻灯片，再将用户提供的逐字稿或 ASR 结果按时间对齐。

默认生成三件正式交付物：

- `slides.pptx`：纯幻灯片 PPT，可包含分节页和 PowerPoint 原生节。
- `slides_viewer.html`：自包含、可编辑的幻灯片＋讲稿查看器。
- `transcript_by_speaker.docx`：带讲者一览表、分节标题和连续正文的 Word 逐字稿；正文中文为宋体 12 磅，英文为 Arial Unicode MS 12 磅。

### 何时使用

- 从 mp4/mkv 等会议、培训或课程视频中提取干净幻灯片。
- 将现有逐字稿或本地 ASR 结果加标点、分段并按时间对齐到幻灯片。
- 生成当前标准的 PPT、可编辑 HTML 和按讲者分节的 Word 逐字稿。
- 识别讲者切换、创建分节，并在三件交付物中统一姓名。

当前标准流程不会把讲稿写入 PPT 备注或右侧文本区；PPT 只保留幻灯片，讲稿的按页对照放在 HTML 中。

### ASR 与 API Key

- **首次运行会对话式配置**：当 Skill 尚未记录转写方式时，Codex 会先在聊天框询问：“云端 ASR（推荐，可能产生少量费用）还是离线 ASR（首次需下载约 1.53 GB 模型文件，耗时较长）？”选择云端后可选千问 Token Plan 或 OpenAI API；选择离线则使用 `faster-whisper medium`。选择保存在用户级配置目录，不写入 Skill 文件夹。
- **API Key 使用隐藏输入**：不要把 Key 粘贴到聊天记录。运行 `python scripts/asr_setup.py wizard`，在本地终端的隐藏输入框中完成配置。Skill 只检查“是否已配置”，不会显示 Key。以后可直接复用，也可以要求 Codex“重新配置 ASR”。
- **当前首选 ASR**：`qwen-audio-3.0-asr-flash`。该模型已包含在阿里云百炼 Token Plan（个人版）的支持模型中；实际可用额度、Credits 抵扣与限流以用户订阅和阿里云控制台为准。标准流程把本地音频切成不超过 5 分钟的片段，通过 DashScope 同步多模态生成端点转写，再执行专名修正、重复/标点清理和抽样 QA。API Key 只从 `DASHSCOPE_API_KEY` 环境变量读取。
- **OpenAI 云端备选**：如果用户已有独立的 OpenAI API Key，可选择 `gpt-4o-mini-transcribe`。Codex 登录或订阅本身不会自动提供该 API 凭证；调用量计入对应的 OpenAI API 项目。
- **离线备选 ASR**：无法或不希望使用云端接口时，可使用本地 `faster-whisper medium`。首次使用需下载约 1.53 GB 模型文件，不产生按时长的 API 调用费，但需要本地计算、存储和电力。
- **可选文本 LLM**：`punctuate_notes.py` 以及 Mode A 的无时间戳内容映射可调用 OpenAI 兼容文本模型，此时需要对应的接口地址和 API Key。

相关官方链接：[注册阿里云账号](https://help.aliyun.com/zh/account/step-1-register-an-alibaba-cloud-account) · [创建百炼 API Key](https://help.aliyun.com/zh/model-studio/get-api-key) · [ASR 模型选型](https://help.aliyun.com/zh/model-studio/asr-model) · [Qwen-ASR API 参考](https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference) · [当前计费与免费额度](https://help.aliyun.com/zh/model-studio/model-pricing)

### 快速安装

1. 将整个文件夹放入 Codex Skills 目录，不要只复制 `SKILL.md`。
2. 创建 Python 3.10 或更高版本的虚拟环境。
3. 安装依赖：

```bash
python -m pip install -r requirements.txt
```

4. 确保 ffmpeg 可用。已安装的 `imageio-ffmpeg` 通常可直接提供；也可使用系统 `PATH` 或 `MEETING_FFMPEG` 环境变量。

详细流程、两种输入模式、参数与已知限制请阅读 [SKILL.md](SKILL.md)；环境与模型说明见 [references/env.md](references/env.md)。

### 分享方式

请分享完整的 Skill 文件夹，至少保留 `SKILL.md`、`scripts/`、`references/`、`agents/`、`requirements.txt`、`README.md`、`SOURCE_VIDEO_NOTICE.md`、`DISCLAIMER.md` 和 `LICENSE`。不要把真实会议视频、转录、输出成果、模型权重或 API 密钥打包进去。

### 基础校验

```bash
python -m unittest discover -s tests -v
```

## English

Meeting Slide Extractor is a Codex Skill that recovers clean slides from meeting, training, lecture, and screen-recording videos. It aligns either a user-supplied transcript or ASR output to the extracted slides.

Its three default deliverables are:

- `slides.pptx`: a clean slide deck, optionally including divider slides and native PowerPoint sections.
- `slides_viewer.html`: a self-contained, editable slide-and-transcript viewer.
- `transcript_by_speaker.docx`: a formatted Word transcript with a speaker overview, section headings, and continuous body text; body text uses 12 pt SimSun for Chinese and 12 pt Arial Unicode MS for English.

### When to use

- Extract clean slides from mp4/mkv meeting, training, or lecture recordings.
- Punctuate, paragraph, correct, and time-align an existing transcript or local ASR output to the slides.
- Produce the current standard PPT, editable HTML viewer, and speaker-sectioned Word transcript.
- Detect speaker changes, create sections, and keep speaker names consistent across all three deliverables.

The current standard workflow does not place the transcript in PowerPoint speaker notes or a right-hand text panel. The PPT contains slides only; page-by-page slide/transcript reading belongs in the HTML viewer.

### ASR and API keys

- **First-run conversational setup:** when no transcription choice has been saved, Codex first asks whether to use cloud ASR (recommended; may incur a small fee) or offline ASR (downloads roughly 1.53 GB of model files on first use and takes longer). Cloud users can choose Qwen Token Plan or the OpenAI API; offline mode uses `faster-whisper medium`. The choice is saved in a user-level configuration directory, never in the Skill folder.
- **Hidden API-key entry:** do not paste keys into chat history. Run `python scripts/asr_setup.py wizard` and enter the key in the local terminal's hidden prompt. The Skill checks only whether a credential exists and never displays its value. The choice is reused until the user asks to reconfigure ASR.
- **Preferred ASR:** `qwen-audio-3.0-asr-flash`. It is listed among the models supported by Alibaba Cloud Model Studio Token Plan (Personal). Actual availability, Credits deductions, and limits depend on the user's subscription and console. The standard workflow splits local audio into chunks of no more than five minutes, transcribes them through the synchronous DashScope multimodal-generation endpoint, and then performs terminology correction, duplicate/punctuation cleanup, and sampled QA. The API key is read only from `DASHSCOPE_API_KEY`.
- **OpenAI cloud alternative:** users with a separate OpenAI API key may choose `gpt-4o-mini-transcribe`. A Codex login or subscription does not itself supply this API credential; usage is charged to the associated OpenAI API project.
- **Offline fallback ASR:** use local `faster-whisper medium` when cloud processing is unavailable or undesirable. Its first run requires roughly 1.53 GB of model files and incurs no per-duration API fee, but uses local compute, storage, and electricity.
- **Optional text LLM:** `punctuate_notes.py` and Mode A mapping for transcripts without timestamps can call an OpenAI-compatible text model. That optional path requires the provider's endpoint and API key.

Official links: [register an Alibaba Cloud account](https://help.aliyun.com/zh/account/step-1-register-an-alibaba-cloud-account) · [create a Model Studio API key](https://help.aliyun.com/zh/model-studio/get-api-key) · [ASR model guide](https://help.aliyun.com/zh/model-studio/asr-model) · [Qwen-ASR API reference](https://help.aliyun.com/zh/model-studio/qwen-asr-api-reference) · [current pricing and free quota](https://help.aliyun.com/zh/model-studio/model-pricing)

### Quick installation

1. Copy the entire folder into your Codex Skills directory. Do not copy only `SKILL.md`.
2. Create a virtual environment with Python 3.10 or newer.
3. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

4. Ensure ffmpeg is available. The installed `imageio-ffmpeg` package will usually provide it; the scripts can also use ffmpeg from `PATH` or the `MEETING_FFMPEG` environment variable.

Read [SKILL.md](SKILL.md) for the complete workflow, operating modes, parameters, and known limitations. See [references/env.md](references/env.md) for environment and model setup.

### Sharing

Share the complete Skill folder, retaining at least `SKILL.md`, `scripts/`, `references/`, `agents/`, `requirements.txt`, `README.md`, `SOURCE_VIDEO_NOTICE.md`, `DISCLAIMER.md`, and `LICENSE`. Do not bundle real meeting videos, transcripts, generated outputs, model weights, or API keys.

### Basic validation

```bash
python -m unittest discover -s tests -v
```

## License / 许可证

This project is licensed under the [MIT License](LICENSE). Copyright © 2026 Staffbao.

本项目采用 [MIT License](LICENSE)。版权所有 © 2026 Staffbao。MIT 许可适用于本 Skill 的代码和文档；它不会授予任何输入视频或其内容的权利，详见 [视频来源与内容权利声明](SOURCE_VIDEO_NOTICE.md)。
