# Qwen 视频复刻 HTML 游戏

这是一个本地 Streamlit 原型项目：上传一段简短的游戏视频，用 Ollama 中运行的 Qwen 多模态模型理解画面玩法，再生成一个可直接在浏览器中运行的单文件 HTML5 Canvas 小游戏。

项目参考了 `ref_link.txt` 中的 DataCamp 文章思路：

https://www.datacamp.com/fr/tutorial/qwen-3-5-small-models-tutorial

核心链路是：视频抽帧 -> 推断结构化游戏规格 -> 生成 HTML 游戏 -> 在 Streamlit 中预览和下载。

## 功能特性

- 支持上传 `mp4`、`mov`、`avi`、`mkv`、`webm` 格式的视频。
- 使用 OpenCV 从视频中均匀抽取 3 到 8 帧。
- 默认调用本地 Ollama 模型 `qwen3.5:9b`。
- 先生成结构化 `GameSpec` JSON，包含实体、控制方式、物理规则、计分规则、胜负条件等。
- 再根据 JSON 规格生成完整的单文件 HTML5 Canvas 游戏。
- 支持在 Streamlit 页面中直接试玩。
- 支持下载生成的 HTML 游戏和 JSON 规格文件。
- 自动修补生成的 HTML，让键盘控制在 Streamlit iframe 预览中更稳定。

## 文件结构

```text
.
├── .python-version # pyenv 固定的 Python 版本
├── app.py           # Streamlit 应用和完整生成流水线
├── pyproject.toml   # Poetry 项目元数据和依赖声明
├── poetry.lock      # Poetry 锁定的完整依赖图
├── requirements.txt # Python 依赖
├── ref_link.txt     # 参考文章链接
└── 技术文章.md       # 中文技术文章
```

生成结果会保存到：

```text
outputs_local/
├── game_spec.json
└── generated_game.html
```

## 环境要求

- pyenv
- Poetry
- Python 3.12.13，已通过 `.python-version` 固定
- 本地已安装 Ollama
- Ollama 中可用 Qwen 3.5 模型，例如 `qwen3.5:9b`

先拉取或启动模型：

```bash
ollama run qwen3.5:9b
```

## 使用 pyenv + Poetry 安装依赖

先安装项目固定的 Python 版本：

```bash
pyenv install -s 3.12.13
pyenv local 3.12.13
```

再创建项目内 Poetry 虚拟环境并安装依赖：

```bash
poetry config virtualenvs.in-project true --local
poetry env use "$(pyenv which python)"
poetry install
```

## 启动项目

```bash
poetry run streamlit run app.py
```

启动后打开终端中显示的地址，通常是：

```text
http://localhost:8501
```

## 工作原理

整个项目分成两次模型调用。

第一步是视频理解。`app.py` 用 OpenCV 从上传的视频中抽取少量关键帧，将这些图片和提示词一起发送给本地 Qwen 模型。模型需要返回严格的 JSON，用来描述一个最小可玩的游戏原型。

第二步是代码生成。程序用 Pydantic 校验 JSON 结构后，把这份游戏规格转换成代码生成提示词，再让模型输出完整 HTML 文档。最终结果包含内联 CSS、JavaScript 和 Canvas 渲染逻辑，不依赖外部资源。

这种“先规格，后代码”的设计更容易排查问题。如果生成的游戏不符合预期，可以先查看 `outputs_local/game_spec.json`，判断问题出在画面理解阶段，还是代码生成阶段。

## 使用建议

- 尽量上传较短、画面清晰、规则明确的视频。
- Pong、Breakout、Flappy Bird、跑酷、躲避类等 2D 小游戏更容易生成成功。
- 复杂 3D 游戏、重 UI 游戏、多角色多关卡游戏通常只能得到简化版近似实现。
- 如果预览区键盘没有响应，先点击一次游戏画布再操作。

## 常见问题

如果缺少依赖：

```bash
poetry install
```

如果模型调用失败，先确认 Ollama 正在运行，并且模型存在：

```bash
ollama list
ollama run qwen3.5:9b
```

如果 JSON 校验失败，可以尝试：

- 换一段更短的视频。
- 增加抽帧数量。
- 在侧边栏填写更明确的玩法提示。

## requirements.txt 说明

`requirements.txt` 仍然保留，方便临时使用 pip 环境；但当前项目推荐使用 Poetry，因为 `poetry.lock` 可以锁定完整依赖版本，更适合复现开发环境。

## 相关文档

- [技术文章.md](./技术文章.md)：中文技术实现说明。
- [ref_link.txt](./ref_link.txt)：参考文章链接。
