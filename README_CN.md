# Qwen 视频复刻 HTML 游戏

一个本地、可观测的视频转游戏工作台，使用 FastAPI、Ollama 和 Qwen，把短游戏视频复刻成可玩的单文件 HTML5 Canvas 小游戏。

流程被拆成显式阶段：上传视频 → 检查抽帧 → 查看模型输入 → 生成并编辑 `game_spec.json` → 生成 HTML → Playwright 校验 → 试玩与迭代。

参考文章：
https://www.datacamp.com/fr/tutorial/qwen-3-5-small-models-tutorial

## 功能特性

- 支持上传 `mp4`、`mov`、`avi`、`mkv`、`webm` 格式的视频。
- 每次上传视频创建持久化 Project，中间产物版本化管理。
- 抽帧后直接展示每一帧画面，用户可判断输入质量。
- 每次 LLM 调用前展示完整输入：system prompt、user prompt、模型参数、图片数量。
- 全程 NDJSON 流式输出：玩法提示 → GameSpec draft → 完整 HTML。
- 视觉理解与代码生成解耦：图片 → 玩法提示 → 文本 → SpecDraft → 服务端展开完整 GameSpec。
- 在 JSON 编辑器里手动修改 GameSpec，或用聊天方式让模型修改。
- 生成完整独立的单文件 HTML5 Canvas 游戏（无外部依赖）。
- **双 LLM provider 支持**：Ollama（本地）做 hint/spec，DeepSeek API（或 Ollama）做 HTML 生成。
- Playwright 浏览器级校验：canvas 存在性、输入响应、画面变化、控制台/页面错误。
- 自动修补 iframe 键盘焦点，方向键和空格键在预览中正常工作。
- 支持 iframe 试玩和下载单文件 HTML。

## 演示

**1. 生成玩法提示和 GameSpec**

https://github.com/user-attachments/assets/26b87361-fe55-4865-a91f-037b54c2718e

**2. 生成单文件 HTML 游戏**

https://github.com/user-attachments/assets/2c526d2a-1cb2-4177-8f2d-36a158a3def0

**3. 最终可玩游戏**

https://github.com/user-attachments/assets/749483a5-adf5-40cc-82a9-914506c874f3

`example_videos/` 目录下有测试用的样例视频。

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | FastAPI + Uvicorn |
| 前端 | 原生 HTML、CSS、JavaScript |
| 视频处理 | OpenCV |
| 本地模型 | Ollama（hint/spec 用 `qwen3.5:9b`，HTML 用 `gemma4:e4b`） |
| 云端模型 | DeepSeek API（可选，用于 HTML 生成） |
| 结构校验 | Pydantic |
| 浏览器校验 | Playwright（headless Chromium） |
| 环境管理 | pyenv + Poetry |

## 文件结构

```text
.
├── app.py              # FastAPI 应用和路由
├── llm.py              # Ollama 和 DeepSeek 流式聊天封装
├── models.py           # Pydantic 模型（GameSpec、SpecDraft、请求体）
├── pipeline.py         # 抽帧、规格解析、HTML 修补、Playwright 校验
├── prompts.py          # system / user prompt 模板
├── static/
│   ├── index.html      # 单页工作台界面
│   ├── styles.css
│   └── app.js          # 前端逻辑：流式处理、状态管理、项目管理
├── demo/               # 演示录屏
├── example_videos/     # 测试用样例视频
├── pyproject.toml
├── poetry.lock
├── requirements.txt
├── .env.example        # API key 配置模板
└── .python-version
```

生成结果保存在 `outputs_local/projects/`。每个 Project 包含：

```text
source.mp4
frames/
specs/                  # 版本化 spec_{编号}_{原因}.json + current.json
html/                   # 版本化 game_{编号}.html + current.html
project.json            # 清单：状态、元信息、产物索引
```

## 环境要求

- pyenv + Poetry
- Python 3.12.13，已通过 `.python-version` 固定
- 本地安装 Ollama，并有可用模型（如 `qwen3.5:9b`、`gemma4:e4b`）
- Playwright Chromium 浏览器（执行 `playwright install chromium` 安装）

先拉取模型：

```bash
ollama run qwen3.5:9b
ollama run gemma4:e4b     # 可选，用于 HTML 生成
```

如需使用 DeepSeek API（可选的 HTML 生成 provider），复制 `.env.example` 为 `.env` 并填入 key：

```bash
cp .env.example .env
# 编辑 .env：DEEPSEEK_API_KEY=你的key
```

## 安装

```bash
pyenv install -s 3.12.13
pyenv local 3.12.13
poetry config virtualenvs.in-project true --local
poetry env use "$(pyenv which python)"
poetry install
playwright install chromium
```

## 启动

```bash
poetry run uvicorn app:app --host 127.0.0.1 --port 8501 --reload
```

打开：

```text
http://127.0.0.1:8501
```

## 使用流程

1. **上传**一段短游戏视频 → 创建持久化 Project。
2. **抽取关键帧**，检查是否覆盖关键玩法状态。
3. **步骤 1 — 玩法提示**：查看模型输入（system prompt、带图片的 user prompt），流式生成中文玩法描述。
4. **步骤 2 — GameSpec 生成**：查看纯文本 prompt，生成精简 JSON draft，服务端展开为完整 GameSpec。
5. **编辑** GameSpec：在 JSON 编辑器中手动修改，或用聊天面板让模型修改特定字段。
6. **步骤 3 — HTML 生成**：选择 provider（Ollama 或 DeepSeek）和模型，查看 prompt，流式生成完整 HTML 游戏。
7. **校验**：Playwright 在 headless Chromium 中打开 HTML，点击开始，发送方向键，采样 canvas 像素，检查画面变化和错误。
8. **试玩**：在 iframe 预览中玩游戏，下载单文件 HTML，或用聊天面板描述 bug 让模型修复。

Project 持久化在本地。重新打开应用后，自动恢复 Project 列表、视频、抽帧、当前 GameSpec、当前 HTML 和历史产物。

## 设计说明

核心目标是降低黑盒感，而非追求全自动：

- 每个阶段有独立触发按钮，不会自动一路跑到底。
- 每次 LLM 调用的输入（prompt、模型、参数、图片数量）在生成前完全可见。
- `SpecDraft` 是小模型能稳定输出的扁平中间格式，服务端负责展开为完整 `GameSpec`。
- HTML 生成可独立切换模型/provider，与 hint/spec 阶段解耦。
- NDJSON 流式输出让用户实时感知模型进度。
- Playwright 校验关注真正重要的东西：canvas 是否存在、输入是否有响应、有没有控制台错误。
- 不使用数据库——`outputs_local/projects/` 是唯一数据源。

## 使用建议

- 尽量上传 5-15 秒的短视频。
- Snake、Pong、Breakout、Flappy Bird、跑酷、躲避类等 2D 小游戏效果更稳定。
- 复杂 3D 游戏、多角色多关卡游戏通常只能生成简化版原型。
- 建议上传前用 ffmpeg 缩放到 480p 或 640p。
- `requirements.txt` 仍然保留，方便临时用 pip；推荐使用 Poetry，因为 `poetry.lock` 可锁定完整依赖版本。
