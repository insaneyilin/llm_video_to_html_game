# Qwen Video to HTML Game

A local Streamlit prototype that turns a short gameplay video into a playable single-file HTML5 Canvas game with Ollama and Qwen.

The project follows the workflow from the reference article in `ref_link.txt`: extract a few representative frames from an uploaded video, ask a local multimodal Qwen model to infer a structured game specification, then ask the model to generate a minimal browser game from that specification.

Reference article:
https://www.datacamp.com/fr/tutorial/qwen-3-5-small-models-tutorial

## Features

- Upload gameplay videos in `mp4`, `mov`, `avi`, `mkv`, or `webm` format.
- Extract 3 to 8 video frames with OpenCV.
- Use a local Ollama model, defaulting to `qwen3.5:9b`.
- Infer a structured `GameSpec` JSON with entities, controls, physics, scoring, and win/lose conditions.
- Generate a complete standalone HTML5 Canvas game.
- Preview the game directly inside Streamlit.
- Download both the generated HTML game and the inferred JSON spec.
- Patch generated HTML so keyboard controls work inside Streamlit iframe previews.

## Project Files

```text
.
├── .python-version # pyenv Python version pin
├── app.py           # Streamlit application and generation pipeline
├── pyproject.toml   # Poetry project metadata and dependencies
├── poetry.lock      # Locked dependency graph
├── requirements.txt # Python dependencies
├── ref_link.txt     # Source article URL
└── 技术文章.md       # Chinese technical article
```

Generated files are saved to:

```text
outputs_local/
├── game_spec.json
└── generated_game.html
```

## Requirements

- pyenv
- Poetry
- Python 3.12.13, pinned by `.python-version`
- Ollama installed locally
- A Qwen 3.5 model available in Ollama, for example `qwen3.5:9b`

Pull or start the model first:

```bash
ollama run qwen3.5:9b
```

## Installation With pyenv + Poetry

Install the pinned Python version:

```bash
pyenv install -s 3.12.13
pyenv local 3.12.13
```

Create the project-local Poetry virtual environment and install dependencies:

```bash
poetry config virtualenvs.in-project true --local
poetry env use "$(pyenv which python)"
poetry install
```

## Run

```bash
poetry run streamlit run app.py
```

Then open the Streamlit URL shown in the terminal, usually:

```text
http://localhost:8501
```

## How It Works

The pipeline has two model calls:

1. Video understanding

   `app.py` samples frames from the uploaded video and sends them to the local Qwen model. The model returns strict JSON describing a small playable game.

2. Code generation

   The validated JSON spec is converted into a code-generation prompt. The model returns a complete HTML document with inline CSS and JavaScript.

This two-step design makes the result easier to debug. If the final game is wrong, you can inspect `game_spec.json` to see whether the issue came from visual understanding or from code generation.

## Notes

- Short clips with clear 2D gameplay work best.
- Simple arcade games such as Pong, Breakout, dodgers, runners, and Flappy Bird style games are more reliable than complex 3D or UI-heavy games.
- The generated game is a simplified playable approximation, not a high-fidelity clone.
- If the preview does not respond to keyboard input, click once inside the game canvas.

## Troubleshooting

If Streamlit cannot import OpenCV or Streamlit:

```bash
poetry install
```

If model generation fails, confirm Ollama is running and the configured model exists:

```bash
ollama list
ollama run qwen3.5:9b
```

If JSON validation fails, try reducing ambiguity:

- Upload a shorter gameplay clip.
- Increase the extracted frame count.
- Add a stronger gameplay hint in the sidebar.

## Optional requirements.txt

`requirements.txt` is kept for simple pip-based environments, but the recommended project setup is Poetry because `poetry.lock` gives reproducible dependency versions.
