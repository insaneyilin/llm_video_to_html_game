"""
Qwen Video to HTML Game — FastAPI application.

Pipeline: upload video -> extract frames -> gameplay hint -> GameSpec -> HTML game.
"""

import json
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from llm import ollama_chat_complete, stream_chat_with_heartbeat
from models import (
    ExtractRequest,
    GameSpec,
    HintRequest,
    HtmlEditRequest,
    HtmlRequest,
    SpecEditRequest,
    SpecRequest,
    ensure_string_list,
)
from pipeline import (
    extract_frames,
    extract_json_object,
    expand_spec_draft,
    game_spec_to_draft,
    generic_spec_from_hint,
    load_frame_images,
    parse_gameplay_hint,
    parse_spec_draft,
    prepare_full_html_output,
    strip_server_html_patch,
    validate_html_game_output,
    validate_html_with_playwright,
    video_metadata,
)
from prompts import (
    FULL_HTML_SYSTEM_PROMPT,
    HINT_SYSTEM_PROMPT,
    HTML_EDIT_SYSTEM_PROMPT,
    SPEC_DRAFT_SYSTEM_PROMPT,
    SPEC_EDIT_SYSTEM_PROMPT,
    build_full_html_prompt,
    build_hint_prompt,
    build_html_edit_prompt,
    build_spec_edit_prompt,
    build_spec_prompt,
)


BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")
STATIC_DIR = BASE_DIR / "static"
PROJECTS_DIR = BASE_DIR / "outputs_local" / "projects"
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

SPEC_NUM_CTX = 8192
HTML_NUM_CTX = 32768
HTML_NUM_PREDICT = 32768

app = FastAPI(title="Qwen Video to HTML Game")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# --- Helpers ---

def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_id(value: str) -> str:
    if "/" in value or ".." in value:
        raise HTTPException(status_code=400, detail="Invalid project id.")
    return value


def project_path(project_id: str) -> Path:
    path = PROJECTS_DIR / safe_id(project_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Project not found.")
    return path


def read_project(project_id: str) -> dict[str, Any]:
    manifest = project_path(project_id) / "project.json"
    if not manifest.exists():
        raise HTTPException(status_code=404, detail="Project manifest not found.")
    return json.loads(manifest.read_text(encoding="utf-8"))


def write_project(project_id: str, project: dict[str, Any]) -> None:
    project["updated_at"] = now_iso()
    (project_path(project_id) / "project.json").write_text(
        json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def project_for_client(project: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(project, ensure_ascii=False))
    out.pop("video_path", None)
    for frame in out.get("frames", []):
        frame.pop("image_base64", None)
    return out


def ndjson_event(event: str, data: Any) -> str:
    return json.dumps({"event": event, "data": data}, ensure_ascii=False) + "\n"


def provider_label(provider: str) -> str:
    return "DeepSeek" if provider == "deepseek" else "Ollama"


def save_spec_version(project_id: str, project: dict[str, Any], spec: dict[str, Any], reason: str) -> str:
    specs_dir = project_path(project_id) / "specs"
    specs_dir.mkdir(exist_ok=True)
    version = len(project.get("artifacts", {}).get("spec_versions", [])) + 1
    filename = f"spec_{version:03d}_{reason}.json"
    content = json.dumps(spec, indent=2, ensure_ascii=False)
    (specs_dir / filename).write_text(content, encoding="utf-8")
    (specs_dir / "current.json").write_text(content, encoding="utf-8")
    project["game_spec"] = spec
    project["current_spec"] = "specs/current.json"
    project.setdefault("artifacts", {}).setdefault("spec_versions", []).append(
        {"version": version, "reason": reason, "path": f"specs/{filename}", "created_at": now_iso()}
    )
    project["status"]["spec_generated"] = True
    return f"specs/{filename}"


def save_html_version(project_id: str, project: dict[str, Any], html: str) -> str:
    html_dir = project_path(project_id) / "html"
    html_dir.mkdir(exist_ok=True)
    version = len(project.get("artifacts", {}).get("html_versions", [])) + 1
    filename = f"game_{version:03d}.html"
    (html_dir / filename).write_text(html, encoding="utf-8")
    (html_dir / "current.html").write_text(html, encoding="utf-8")
    project["current_html"] = "html/current.html"
    project.setdefault("artifacts", {}).setdefault("html_versions", []).append(
        {"version": version, "path": f"html/{filename}", "created_at": now_iso()}
    )
    project["status"]["html_generated"] = True
    return f"html/{filename}"


# --- Routes ---

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/projects")
def list_projects() -> JSONResponse:
    projects = []
    for manifest in PROJECTS_DIR.glob("*/project.json"):
        try:
            p = json.loads(manifest.read_text(encoding="utf-8"))
            projects.append({
                "id": p["id"], "name": p["name"],
                "original_filename": p.get("original_filename"),
                "created_at": p.get("created_at"), "updated_at": p.get("updated_at"),
                "status": p.get("status", {}),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    projects.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
    return JSONResponse({"projects": projects})


@app.post("/api/projects/upload")
async def upload_project(file: UploadFile = File(...)) -> JSONResponse:
    suffix = Path(file.filename or "video.mp4").suffix or ".mp4"
    stem = Path(file.filename or "video").stem[:40].replace(" ", "-") or "video"
    project_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    pdir = PROJECTS_DIR / project_id
    pdir.mkdir(parents=True, exist_ok=True)
    for d in ("frames", "specs", "html"):
        (pdir / d).mkdir(exist_ok=True)
    video_path = pdir / f"source{suffix}"
    with video_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    try:
        metadata = video_metadata(video_path)
    except ValueError as e:
        shutil.rmtree(pdir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(e)) from e

    project = {
        "id": project_id, "name": stem,
        "created_at": now_iso(), "updated_at": now_iso(),
        "original_filename": file.filename,
        "video_path": str(video_path),
        "video_url": f"/api/projects/{project_id}/video",
        "metadata": metadata,
        "status": {"video_uploaded": True, "frames_extracted": False, "spec_generated": False, "html_generated": False},
        "frames": [], "game_hint": "", "game_spec": None, "current_spec": None, "current_html": None,
        "artifacts": {"spec_versions": [], "html_versions": []},
    }
    write_project(project_id, project)
    return JSONResponse(project_for_client(project))


@app.get("/api/projects/{project_id}")
def get_project(project_id: str) -> JSONResponse:
    return JSONResponse(project_for_client(read_project(project_id)))


@app.get("/api/projects/{project_id}/video")
def get_video(project_id: str) -> FileResponse:
    return FileResponse(read_project(project_id)["video_path"])


@app.post("/api/projects/{project_id}/extract")
def extract_project_frames(project_id: str, request: ExtractRequest) -> JSONResponse:
    project = read_project(project_id)
    frames = extract_frames(
        Path(project["video_path"]),
        project_path(project_id) / "frames",
        project_id,
        request.max_frames,
    )
    project["frames"] = frames
    project["status"]["frames_extracted"] = True
    write_project(project_id, project)
    return JSONResponse({
        "project": project_for_client(project),
        "frames": [{k: v for k, v in f.items() if k != "image_base64"} for f in frames],
        "metadata": project["metadata"],
    })


@app.get("/api/projects/{project_id}/frames/{filename}")
def get_frame(project_id: str, filename: str) -> FileResponse:
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    frame_path = project_path(project_id) / "frames" / filename
    if not frame_path.exists():
        raise HTTPException(status_code=404, detail="Frame not found.")
    return FileResponse(frame_path)


# --- Hint ---

@app.post("/api/projects/{project_id}/hint/input")
def get_hint_input(project_id: str, request: HintRequest) -> JSONResponse:
    frames = load_frame_images(project_path(project_id) / "frames", request.max_frames)
    return JSONResponse({
        "system_prompt": HINT_SYSTEM_PROMPT,
        "user_prompt": build_hint_prompt(request.max_frames, request.user_notes),
        "model": request.model,
        "frame_count": len(frames),
    })


@app.post("/api/projects/{project_id}/hint/stream")
def generate_gameplay_hint(project_id: str, request: HintRequest) -> StreamingResponse:
    frames = load_frame_images(project_path(project_id) / "frames", request.max_frames)
    user_prompt = build_hint_prompt(request.max_frames, request.user_notes)
    messages = [
        {"role": "system", "content": HINT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt, "images": frames},
    ]

    def generate() -> Iterable[str]:
        yield ndjson_event("meta", {
            "stage": "hint", "status": "calling_model",
            "model": request.model, "frame_count": len(frames),
            "message": f"Calling {request.model} with {len(frames)} frames...",
        })
        raw_content = ""
        try:
            for event, payload in stream_chat_with_heartbeat(
                provider="ollama", model=request.model, messages=messages,
                options={"temperature": 0.1, "num_ctx": SPEC_NUM_CTX},
                response_format="json", think=False, first_chunk_timeout_seconds=60,
            ):
                if event == "heartbeat":
                    yield ndjson_event("meta", {
                        "stage": "hint", "status": "waiting_model",
                        "elapsed_seconds": payload,
                        "message": f"Waiting for model... {payload}s elapsed.",
                    })
                    continue
                delta, full_content, think_delta = payload
                raw_content = full_content
                if delta:
                    yield ndjson_event("delta", delta)

            hint = parse_gameplay_hint(raw_content)
            project = read_project(project_id)
            project["game_hint"] = hint
            write_project(project_id, project)
            yield ndjson_event("final", {"project": project_for_client(project), "game_hint": hint})
        except Exception as error:
            yield ndjson_event("error", str(error))

    return StreamingResponse(generate(), media_type="application/x-ndjson")


# --- Spec ---

@app.post("/api/projects/{project_id}/spec/input")
def get_spec_input(project_id: str, request: SpecRequest) -> JSONResponse:
    gameplay_brief = request.game_hint.strip()
    if not gameplay_brief:
        raise HTTPException(status_code=400, detail="Generate or enter a gameplay hint first.")
    return JSONResponse({
        "system_prompt": SPEC_DRAFT_SYSTEM_PROMPT,
        "user_prompt": build_spec_prompt(gameplay_brief, request.extra_constraints),
        "model": request.model,
    })


@app.post("/api/projects/{project_id}/spec/stream")
def generate_spec(project_id: str, request: SpecRequest) -> StreamingResponse:
    gameplay_brief = request.game_hint.strip()
    if not gameplay_brief:
        raise HTTPException(status_code=400, detail="Generate or enter a gameplay hint first.")

    def generate() -> Iterable[str]:
        user_prompt = build_spec_prompt(gameplay_brief, request.extra_constraints)
        yield ndjson_event("meta", {
            "stage": "spec", "status": "calling_model", "model": request.model,
            "message": f"Calling {request.model} for compact GameSpec draft...",
        })

        raw_output = ""
        spec_source = "llm_draft"
        try:
            for event, payload in stream_chat_with_heartbeat(
                provider="ollama", model=request.model,
                messages=[
                    {"role": "system", "content": SPEC_DRAFT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                options={"temperature": 0.0, "num_ctx": SPEC_NUM_CTX, "num_predict": 700},
                response_format="json", think=False, first_chunk_timeout_seconds=30,
            ):
                if event == "heartbeat":
                    yield ndjson_event("meta", {
                        "stage": "spec", "status": "waiting_model",
                        "elapsed_seconds": payload,
                        "message": f"Waiting for spec draft... {payload}s elapsed.",
                    })
                    continue
                delta, full_content, _ = payload
                raw_output = full_content
                if delta:
                    yield ndjson_event("delta", delta)

            if not raw_output.strip():
                raise ValueError("Model returned empty output.")
            draft = parse_spec_draft(raw_output)
            spec = expand_spec_draft(draft, gameplay_brief)
        except Exception as e:
            spec_source = "generic_fallback"
            spec = generic_spec_from_hint(gameplay_brief)
            yield ndjson_event("meta", {
                "stage": "spec", "status": "fallback",
                "message": f"LLM draft failed ({e}). Using generic fallback.",
            })

        yield ndjson_event("full", json.dumps(spec, indent=2, ensure_ascii=False))

        project = read_project(project_id)
        project["game_hint"] = gameplay_brief
        save_spec_version(project_id, project, spec, "initial")
        write_project(project_id, project)
        yield ndjson_event("final", {"project": project_for_client(project), "game_spec": spec})

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.post("/api/projects/{project_id}/spec/chat/stream")
def edit_spec(project_id: str, request: SpecEditRequest) -> StreamingResponse:
    draft = game_spec_to_draft(request.current_spec)
    draft_json = json.dumps(draft.model_dump(), indent=2, ensure_ascii=False)
    user_prompt = build_spec_edit_prompt(draft_json, request.user_message)
    messages = [
        {"role": "system", "content": SPEC_EDIT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    def generate() -> Iterable[str]:
        yield ndjson_event("meta", {
            "stage": "spec_edit", "status": "calling_model",
            "message": f"Calling {request.model} to edit GameSpec...",
        })
        try:
            raw_output = ollama_chat_complete(
                model=request.model, messages=messages,
                options={"temperature": 0.0, "num_ctx": SPEC_NUM_CTX, "num_predict": 700},
                response_format="json", think=False,
            )
            new_draft = parse_spec_draft(raw_output)
            project = read_project(project_id)
            spec = expand_spec_draft(new_draft, project.get("game_hint", ""), baseline_spec=request.current_spec)
            spec["confidence_notes"] = ensure_string_list(request.current_spec.get("confidence_notes"))
            spec["confidence_notes"].append("Updated via chat edit")

            yield ndjson_event("delta", json.dumps(spec, indent=2, ensure_ascii=False))
            save_spec_version(project_id, project, spec, "chat_edit")
            write_project(project_id, project)
            yield ndjson_event("final", {"project": project_for_client(project), "game_spec": spec})
        except Exception as error:
            yield ndjson_event("error", str(error))

    return StreamingResponse(generate(), media_type="application/x-ndjson")


# --- HTML generation ---

@app.post("/api/projects/{project_id}/html/input")
def get_html_input(project_id: str, request: HtmlRequest) -> JSONResponse:
    GameSpec(**request.game_spec)
    return JSONResponse({
        "provider": request.provider,
        "model": request.model,
        "system_prompt": FULL_HTML_SYSTEM_PROMPT,
        "user_prompt": build_full_html_prompt(request.game_spec),
    })


@app.post("/api/projects/{project_id}/html/stream")
def generate_html(project_id: str, request: HtmlRequest) -> StreamingResponse:
    GameSpec(**request.game_spec)

    def generate() -> Iterable[str]:
        stop_event = threading.Event()
        user_prompt = build_full_html_prompt(request.game_spec)
        messages = [
            {"role": "system", "content": FULL_HTML_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        yield ndjson_event("meta", {
            "stage": "html", "status": "calling_model",
            "provider": request.provider, "model": request.model,
            "message": f"Calling {provider_label(request.provider)} {request.model} to generate HTML game...",
        })

        raw_output = ""
        try:
            for event, payload in stream_chat_with_heartbeat(
                provider=request.provider, model=request.model, messages=messages,
                options={"temperature": 0.15, "num_ctx": HTML_NUM_CTX, "num_predict": HTML_NUM_PREDICT},
                think=False, first_chunk_timeout_seconds=60, stop_event=stop_event,
            ):
                if event == "heartbeat":
                    yield ndjson_event("meta", {
                        "stage": "html", "status": "waiting_model",
                        "elapsed_seconds": payload,
                        "message": f"Waiting for HTML tokens... {payload}s elapsed.",
                    })
                    continue
                delta, full_content, think_delta = payload
                raw_output = full_content
                if think_delta:
                    yield ndjson_event("think_delta", think_delta)
                if delta:
                    yield ndjson_event("module_delta", {"attempt": 1, "mode": "full_html", "delta": delta})

            if not raw_output.strip():
                raise ValueError("Model returned empty HTML.")

            html = prepare_full_html_output(raw_output)

            yield ndjson_event("meta", {
                "stage": "html", "status": "validating",
                "message": "Validating generated HTML with Playwright...",
            })
            validate_html_game_output(html)
            validation = validate_html_with_playwright(html)
            yield ndjson_event("validation", {"attempt": 1, "ok": True, "stage": "passed", "message": str(validation)})

            project = read_project(project_id)
            save_html_version(project_id, project, html)
            write_project(project_id, project)

            yield ndjson_event("full", html)
            yield ndjson_event("final", {
                "project": project_for_client(project),
                "html": html,
                "download_url": f"/api/projects/{project_id}/html/download",
                "preview_url": f"/api/projects/{project_id}/html/preview",
            })
        except Exception as error:
            yield ndjson_event("error", str(error))
        finally:
            stop_event.set()

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.post("/api/projects/{project_id}/html/chat/stream")
def edit_html(project_id: str, request: HtmlEditRequest) -> StreamingResponse:
    if not request.current_html.strip():
        raise HTTPException(status_code=400, detail="Current HTML is empty.")
    if not request.user_message.strip():
        raise HTTPException(status_code=400, detail="Fix request is empty.")

    project = read_project(project_id)
    gameplay_hint = request.gameplay_hint.strip() or project.get("game_hint", "")
    prepared_html = strip_server_html_patch(request.current_html.strip())
    user_prompt = build_html_edit_prompt(prepared_html, request.user_message.strip(), gameplay_hint)
    messages = [
        {"role": "system", "content": HTML_EDIT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    def generate() -> Iterable[str]:
        stop_event = threading.Event()
        yield ndjson_event("meta", {
            "stage": "html_edit", "status": "calling_model",
            "provider": request.provider, "model": request.model,
            "message": f"Calling {provider_label(request.provider)} {request.model} to fix HTML...",
        })
        raw_content = ""
        try:
            for event, payload in stream_chat_with_heartbeat(
                provider=request.provider, model=request.model, messages=messages,
                options={"temperature": 0.15, "num_ctx": HTML_NUM_CTX, "num_predict": HTML_NUM_PREDICT},
                think=False, first_chunk_timeout_seconds=60, stop_event=stop_event,
            ):
                if event == "heartbeat":
                    yield ndjson_event("meta", {
                        "stage": "html_edit", "status": "waiting_model",
                        "elapsed_seconds": payload,
                        "message": f"Waiting for fixed HTML... {payload}s elapsed.",
                    })
                    continue
                delta, full_content, think_delta = payload
                raw_content = full_content
                if think_delta:
                    yield ndjson_event("think_delta", think_delta)
                if delta:
                    yield ndjson_event("delta", delta)

            if not raw_content.strip():
                raise ValueError("Model returned empty HTML.")
            html = prepare_full_html_output(raw_content)
            validate_html_game_output(html)

            yield ndjson_event("full", html)
            project = read_project(project_id)
            save_html_version(project_id, project, html)
            write_project(project_id, project)
            yield ndjson_event("final", {
                "project": project_for_client(project),
                "html": html,
                "download_url": f"/api/projects/{project_id}/html/download",
                "preview_url": f"/api/projects/{project_id}/html/preview",
            })
        except Exception as error:
            yield ndjson_event("error", str(error))
        finally:
            stop_event.set()

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@app.get("/api/projects/{project_id}/html/preview")
def preview_html(project_id: str) -> FileResponse:
    project = read_project(project_id)
    if not project.get("current_html"):
        raise HTTPException(status_code=404, detail="HTML game not generated.")
    return FileResponse(project_path(project_id) / project["current_html"], media_type="text/html")


@app.get("/api/projects/{project_id}/html/download")
def download_html(project_id: str) -> FileResponse:
    project = read_project(project_id)
    if not project.get("current_html"):
        raise HTTPException(status_code=404, detail="HTML game not generated.")
    return FileResponse(
        project_path(project_id) / project["current_html"],
        filename=f"{project['name']}_game.html",
        media_type="text/html",
    )
