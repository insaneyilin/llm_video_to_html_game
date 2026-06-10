# Qwen Video to HTML Game

A local, observable video-to-game workbench powered by FastAPI, Ollama, and Qwen.

The app turns a short gameplay video into a playable single-file HTML5 Canvas game, but it no longer hides the process behind one long spinner. The workflow is split into explicit stages: upload video, inspect extracted frames, review the model input, generate and edit `game_spec.json`, then generate the final HTML game.

Reference article:
https://www.datacamp.com/fr/tutorial/qwen-3-5-small-models-tutorial

## Features

- Upload gameplay videos in `mp4`, `mov`, `avi`, `mkv`, or `webm` format.
- Treat each uploaded video as a persistent Project.
- Automatically load existing Projects when the app opens.
- Extract and inspect representative frames before any LLM call.
- Show the exact system prompt, user prompt, model options, and frame count sent to Ollama.
- Stream LLM output while generating `game_spec.json`.
- Edit the generated GameSpec manually in a JSON editor.
- Ask the model to modify the GameSpec through a chat-style instruction.
- Show the final GameSpec used to prompt the gameplay module generator.
- Generate a gameplay JavaScript module with Ollama, then embed it in a stable single-file Canvas HTML runtime.
- Preview and download the generated single-file HTML5 game.

## Stack

- Backend: FastAPI + Uvicorn
- Frontend: vanilla HTML, CSS, and JavaScript
- Video processing: OpenCV
- LLM runtime: Ollama
- Schema validation: Pydantic
- Environment management: pyenv + Poetry

## Project Files

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

Projects are saved under:

```text
outputs_local/projects/
```

Each Project may contain:

```text
source.mov
frames/
specs/
html/
logs/
project.json
```

## Requirements

- pyenv
- Poetry
- Python 3.12.13, pinned by `.python-version`
- Ollama installed locally
- A Qwen model available in Ollama, for example `qwen3.5:9b`

Pull or start the model first:

```bash
ollama run qwen3.5:9b
```

## Installation

```bash
pyenv install -s 3.12.13
pyenv local 3.12.13
poetry config virtualenvs.in-project true --local
poetry env use "$(pyenv which python)"
poetry install
```

## Run

```bash
poetry run uvicorn app:app --host 127.0.0.1 --port 8501 --reload
```

Open:

```text
http://127.0.0.1:8501
```

## Workflow

1. Open the app and select an existing Project, or upload a short gameplay video to create a new Project.
2. Extract frames and inspect whether they capture the important gameplay states.
3. Review the GameSpec model input: system prompt, user prompt, options, and attached frame count.
4. Generate `game_spec.json` with streaming output.
5. Edit the GameSpec manually or ask the model to revise it through the chat control.
6. Review the GameSpec that will drive the gameplay module prompt.
7. Generate the final HTML game: Ollama writes only `createGameModule(api)`, and the backend validates it inside a fixed Canvas runtime.
8. Preview the game in the browser and download the standalone HTML file.

The app persists every Project on disk. Reopening the app restores the Project list, current video, extracted frames, current GameSpec, current HTML preview, and artifact history.

## Notes

- The app shows model inputs and visible model outputs. It does not expose hidden chain-of-thought.
- No database is used. `outputs_local/projects/` is the source of truth.
- Short, clear 2D gameplay videos work best.
- Simple arcade games such as Snake, Pong, Breakout, runners, and dodgers are more reliable than complex 3D games.
- `requirements.txt` is kept for simple pip-based environments, but Poetry is the recommended setup.
