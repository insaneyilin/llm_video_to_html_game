# Qwen Video to HTML Game

A local, observable video-to-game workbench powered by FastAPI, Ollama, and Qwen.

The app turns a short gameplay video into a playable single-file HTML5 Canvas game through explicit stages: upload video → inspect extracted frames → review model input → generate and edit `game_spec.json` → generate HTML → validate with Playwright → play and iterate.

Reference article:
https://www.datacamp.com/fr/tutorial/qwen-3-5-small-models-tutorial

## Features

- Upload gameplay videos in `mp4`, `mov`, `avi`, `mkv`, or `webm` format.
- Treat each uploaded video as a persistent Project with versioned artifacts.
- Extract and inspect representative frames before any LLM call.
- Show the exact system prompt, user prompt, model options, and image count sent to each LLM call.
- Stream all model output via NDJSON: gameplay hint → GameSpec draft → full HTML.
- Split visual understanding from code generation: `gameplay_hint` from images → `SpecDraft` from text → expanded `GameSpec` on the server.
- Edit the generated GameSpec manually in a JSON editor, or ask the model to revise it through chat.
- Generate a complete standalone HTML5 Canvas game (single-file, no external dependencies).
- Support **dual LLM providers**: Ollama (local) for hint/spec, DeepSeek API (or Ollama) for HTML generation.
- Validate the generated HTML with Playwright: canvas presence, motion after input, console/page errors.
- Patch iframe keyboard focus automatically — arrow keys and spacebar work in preview.
- Preview and download the standalone HTML game.

## Demo

**1. Generate gameplay hint & GameSpec**

<video src="demo/01_generate_game_hint_and_spec_1280.mp4" controls width="100%"></video>

**2. Generate single-file HTML game**

<video src="demo/02_generate_single_html_1280.mp4" controls width="100%"></video>

**3. Final playable game**

<video src="demo/03_final_game_1280.mp4" controls width="100%"></video>

Example videos for testing are in `example_videos/`.

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Uvicorn |
| Frontend | vanilla HTML, CSS, JavaScript |
| Video processing | OpenCV |
| LLM (local) | Ollama (`qwen3.5:9b` for hint/spec, `gemma4:e4b` for HTML) |
| LLM (cloud) | DeepSeek API (optional, for HTML generation) |
| Schema validation | Pydantic |
| Browser validation | Playwright (headless Chromium) |
| Env management | pyenv + Poetry |

## Project Files

```text
.
├── app.py              # FastAPI application & routes
├── llm.py              # Ollama & DeepSeek streaming chat wrappers
├── models.py           # Pydantic models (GameSpec, SpecDraft, requests)
├── pipeline.py         # Frame extraction, spec parsing, HTML patching, Playwright validation
├── prompts.py          # System & user prompt templates
├── static/
│   ├── index.html      # Single-page workbench UI
│   ├── styles.css
│   └── app.js          # Frontend logic: streaming, state, project management
├── demo/               # Demo screencasts
├── example_videos/     # Sample videos for testing
├── pyproject.toml
├── poetry.lock
├── requirements.txt
├── .env.example        # API key configuration template
└── .python-version
```

Projects persist under `outputs_local/projects/`. Each Project contains:

```text
source.mp4
frames/
specs/                  # versioned spec_{n}_{reason}.json + current.json
html/                   # versioned game_{n}.html + current.html
project.json            # manifest with status, metadata, artifact index
```

## Requirements

- pyenv + Poetry
- Python 3.12.13, pinned by `.python-version`
- Ollama installed locally with a model available (e.g. `qwen3.5:9b`, `gemma4:e4b`)
- Playwright Chromium browser (install with `playwright install chromium`)

Pull or start models first:

```bash
ollama run qwen3.5:9b
ollama run gemma4:e4b     # optional, for HTML generation
```

For DeepSeek API (optional HTML generation provider), copy `.env.example` to `.env` and set your key:

```bash
cp .env.example .env
# edit .env: DEEPSEEK_API_KEY=your_key
```

## Installation

```bash
pyenv install -s 3.12.13
pyenv local 3.12.13
poetry config virtualenvs.in-project true --local
poetry env use "$(pyenv which python)"
poetry install
playwright install chromium
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

1. **Upload** a short gameplay video → a persistent Project is created.
2. **Extract frames** and inspect whether they capture key gameplay states.
3. **Step 1 — Gameplay Hint**: review the model input (system prompt, user prompt with images), then generate a Chinese gameplay brief with streaming output.
4. **Step 2 — GameSpec Draft**: review the text-only prompt, generate a compact JSON draft, then the server expands it into a full `GameSpec` with physics/visual defaults.
5. **Edit** the GameSpec manually in the JSON editor, or use the chat panel to ask the model to revise specific fields.
6. **Step 3 — HTML Generation**: choose a provider (Ollama or DeepSeek) and model, review the prompt, then generate the full HTML game with streaming output.
7. **Validation**: Playwright opens the generated HTML in headless Chromium, clicks Start, sends arrow keys, samples canvas pixels, and checks for motion and errors.
8. **Play** the game in the iframe preview, download the standalone HTML file, or use the chat panel to describe bugs and ask the model to fix them.

The app persists every Project on disk. Reopening the app restores the Project list, video, frames, current GameSpec, current HTML, and artifact history.

## Design Notes

The core goal is observability over automation:

- Each stage has an explicit trigger — it won't auto-run to the end.
- Every LLM input (prompt, model, parameters, image count) is visible before generation.
- `SpecDraft` is a flat intermediate format that small models can produce reliably; the server expands it to the full `GameSpec`.
- HTML generation can switch models/providers independently from hint/spec stages.
- Streaming NDJSON gives live feedback so the user knows the model is working.
- Playwright validation checks what matters: canvas exists, game responds to input, no console errors.
- No database — `outputs_local/projects/` is the source of truth.

## Tips

- Short, clear 2D gameplay videos (5-15 seconds) work best.
- Snake, Pong, Breakout, Flappy Bird, runners, and dodgers are more reliable than complex 3D games.
- Consider resizing to 480p or 640p before uploading.
- `requirements.txt` is kept for simple pip-based environments; Poetry is the recommended setup.
