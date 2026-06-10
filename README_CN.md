# Qwen 视频复刻 HTML 游戏

这是一个本地、可观测的视频转游戏工作台，使用 FastAPI、Ollama 和 Qwen，把短游戏视频复刻成可玩的单文件 HTML5 Canvas 小游戏。

这版已经不再使用 Streamlit，也不再把所有步骤塞进一个“等待生成”的黑盒按钮里。新的工作流被拆成明确阶段：上传视频、检查抽帧、查看模型输入、生成并编辑 `game_spec.json`、最后再生成 HTML 游戏。

参考文章：
https://www.datacamp.com/fr/tutorial/qwen-3-5-small-models-tutorial

## 功能特性

- 支持上传 `mp4`、`mov`、`avi`、`mkv`、`webm` 格式的视频。
- 每次上传视频都会创建一个持久化 Project。
- 应用打开时会自动加载已有 Project。
- 先抽取关键帧，并在页面上展示每一帧。
- 在调用 LLM 前展示完整模型输入：system prompt、user prompt、模型参数和图片数量。
- 生成 `game_spec.json` 时实时显示模型输出。
- 支持在 JSON 编辑器中手动修改 GameSpec。
- 支持用聊天式指令让模型修改 GameSpec。
- 生成 HTML 前展示最终用于内置生成器的 GameSpec。
- 使用一个由 GameSpec 参数化的通用 Canvas 模板稳定生成可玩的单文件 HTML。
- 生成完成后支持浏览器内预览和下载单文件 HTML 游戏。

## 技术栈

- 后端：FastAPI + Uvicorn
- 前端：原生 HTML、CSS、JavaScript
- 视频处理：OpenCV
- 本地模型：Ollama
- 结构校验：Pydantic
- 环境管理：pyenv + Poetry

## 文件结构

```text
.
├── .python-version
├── app.py
├── static/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── pyproject.toml
├── poetry.lock
├── requirements.txt
└── ref_link.txt
```

生成结果保存在：

```text
outputs_local/projects/
```

每次上传会创建一个独立 Project，里面可能包含：

```text
source.mov
frames/
specs/
html/
logs/
project.json
```

## 环境要求

- pyenv
- Poetry
- Python 3.12.13，已通过 `.python-version` 固定
- 本地安装 Ollama
- Ollama 中有可用的 Qwen 模型，例如 `qwen3.5:9b`

先拉取或启动模型：

```bash
ollama run qwen3.5:9b
```

## 安装

```bash
pyenv install -s 3.12.13
pyenv local 3.12.13
poetry config virtualenvs.in-project true --local
poetry env use "$(pyenv which python)"
poetry install
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

1. 打开应用后选择已有 Project，或上传一段较短的游戏视频创建新 Project。
2. 点击“抽取关键帧”，检查这些帧是否覆盖关键玩法状态。
3. 点击“查看输入”，检查即将发送给模型的 prompt 和图片数量。
4. 点击“生成 game_spec.json”，流式观察模型输出。
5. 在 JSON 编辑器里手动改规格，或用聊天输入让模型修改规格。
6. 确认规格后，查看 HTML 生成阶段使用的 GameSpec。
7. 点击“生成 HTML 游戏”，由通用可玩 Canvas 模板生成单文件 HTML。
8. 在页面右侧试玩，并下载生成的单文件 HTML。

Project 会持久化在本地文件系统中。重新打开应用后，会自动恢复 Project 列表、当前视频、抽帧结果、当前 GameSpec、当前 HTML 预览和历史产物记录。

## 设计说明

这次重构的核心目标是降低黑盒感：

- 每个阶段都有明确按钮，不会自动一路跑到底。
- 每个视频都是一个 Project，中间过程可追溯，避免重复生成。
- 抽帧结果直接可见，用户可以判断视频输入质量。
- LLM 输入直接可见，用户能理解模型为什么会这样生成。
- GameSpec 是中间产物，既能人工编辑，也能让模型根据自然语言修改。
- HTML 生成只在用户确认规格后进行，减少无效等待。

注意：页面展示的是模型输入和模型可见输出，不展示隐藏 chain-of-thought。

当前实现不使用数据库，`outputs_local/projects/` 就是唯一数据源。

## 使用建议

- 尽量上传短视频，推荐 5 到 15 秒。
- 推荐先用 ffmpeg 缩小到 480p 或 640p。
- Snake、Pong、Breakout、Flappy Bird、跑酷、躲避类等 2D 小游戏效果更稳定。
- 复杂 3D 游戏、多角色多关卡游戏通常只能生成简化版原型。

## requirements.txt 说明

`requirements.txt` 仍然保留，方便临时使用 pip 环境；但当前项目推荐使用 Poetry，因为 `poetry.lock` 可以锁定完整依赖版本，更适合复现开发环境。
