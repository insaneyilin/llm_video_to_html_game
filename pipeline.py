"""Core pipeline logic: frame extraction, spec generation, HTML generation."""

import base64
import json
import re
from pathlib import Path
from typing import Any, List

import cv2

from models import (
    Entity,
    GameplayHint,
    GameSpec,
    Physics,
    SpecDraft,
    VisualStyle,
    ensure_string_list,
)

SERVER_HTML_PATCH_MARKER = "<!-- qwen-video-to-game:keyboard-patch -->"


# --- Video / frames ---

def video_metadata(video_path: Path) -> dict[str, Any]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError("Cannot open uploaded video.")
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = frame_count / fps if fps else 0
    cap.release()
    return {
        "frame_count": frame_count,
        "fps": round(fps, 2),
        "width": width,
        "height": height,
        "duration_seconds": round(duration, 2),
    }


def extract_frames(
    video_path: Path,
    frames_dir: Path,
    project_id: str,
    max_frames: int,
) -> list[dict[str, Any]]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("*.jpg"):
        old.unlink()

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError("Cannot open uploaded video.")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0
    if total_frames <= 0:
        total_frames = max_frames

    sample_indexes = sorted(set(
        int(i * max(1, total_frames - 1) / max(1, max_frames - 1)) for i in range(max_frames)
    ))

    frames = []
    for frame_index in sample_indexes:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            continue
        output_path = frames_dir / f"frame_{len(frames) + 1:02d}.jpg"
        encoded, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        if encoded:
            output_path.write_bytes(buffer.tobytes())
            frames.append({
                "index": frame_index,
                "timestamp_seconds": round(frame_index / fps, 2) if fps else None,
                "filename": output_path.name,
                "url": f"/api/projects/{project_id}/frames/{output_path.name}",
                "image_base64": base64.b64encode(buffer).decode("ascii"),
            })
    cap.release()

    if not frames:
        raise ValueError("No frames could be extracted from the video.")
    return frames


def load_frame_images(frames_dir: Path, max_frames: int | None = None) -> list[str]:
    frames = sorted(frames_dir.glob("*.jpg"))
    if not frames:
        raise ValueError("Extract frames before generating GameSpec.")
    if max_frames and len(frames) > max_frames:
        step = max(1, (len(frames) - 1) / max(1, max_frames - 1))
        frames = [frames[int(i * step)] for i in range(max_frames)]
    return [base64.b64encode(f.read_bytes()).decode("ascii") for f in frames]


# --- Text utilities ---

def strip_code_fence(text: str) -> str:
    html = text.strip()
    if html.startswith("```"):
        lines = html.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        html = "\n".join(lines).strip()
    return html


def extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("The model did not return a JSON object.")
    return text[start: end + 1]


# --- Hint parsing ---

def parse_gameplay_hint(raw_content: str) -> str:
    cleaned = strip_code_fence(raw_content.strip())
    parsed = json.loads(extract_json_object(cleaned))
    hint = GameplayHint(**parsed).gameplay_brief.strip()
    if len(hint) < 20:
        raise ValueError("The gameplay brief is too short.")
    return hint


# --- Spec parsing and expansion ---

def parse_entity_token(line: str) -> Entity:
    text = line.strip()
    if not text:
        return Entity(name="entity", role="environment", behavior="exists")
    if "|" in text:
        parts = [p.strip() for p in text.split("|", 2)]
        while len(parts) < 3:
            parts.append("")
        return Entity(
            name=parts[0] or "entity",
            role=parts[1] or "environment",
            behavior=parts[2] or "interacts in the game",
        )
    return Entity(name=text, role="environment", behavior=text)


def parse_spec_draft(raw_content: str) -> SpecDraft:
    cleaned = strip_code_fence(raw_content.strip())
    parsed = json.loads(extract_json_object(cleaned))
    return SpecDraft(**parsed)


def expand_spec_draft(
    draft: SpecDraft,
    gameplay_brief: str = "",
    baseline_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    entities = [parse_entity_token(line) for line in draft.entities if str(line).strip()]
    if not entities:
        entities = [Entity(name="player", role="player", behavior="controlled by keyboard")]

    physics = Physics(
        gravity="as required by the described game",
        jump_or_impulse="as required by the described controls",
        collision_style="simple playable collision matching the described game",
        movement_style="keyboard-driven movement",
    )
    visual = VisualStyle(
        perspective="simple canvas view matching the described game",
        palette="simple high-contrast arcade colors",
        background="clean playable canvas background",
        ui_elements=["score", "lives or status", "start", "game over"],
    )
    spec = GameSpec(
        title=draft.title.strip() or "Arcade Game",
        genre=draft.genre.strip() or "Arcade",
        objective=draft.objective.strip(),
        player_controls=draft.player_controls,
        gameplay_loop=draft.gameplay_loop,
        entities=entities,
        scoring_rules=draft.scoring_rules,
        win_condition=draft.win_condition.strip(),
        lose_condition=draft.lose_condition.strip(),
        physics=physics,
        visual_style=visual,
        assumptions=[gameplay_brief.strip()] if gameplay_brief.strip() else ["Simplified arcade prototype"],
        confidence_notes=["Generated from compact JSON draft with default physics/visual fields"],
    )
    result = spec.model_dump()
    if baseline_spec:
        if baseline_spec.get("physics"):
            result["physics"] = baseline_spec["physics"]
        if baseline_spec.get("visual_style"):
            result["visual_style"] = baseline_spec["visual_style"]
    return result


def game_spec_to_draft(spec: dict[str, Any]) -> SpecDraft:
    entities: list[str] = []
    for entity in spec.get("entities") or []:
        if isinstance(entity, dict):
            entities.append(
                f"{entity.get('name', 'entity')}|{entity.get('role', 'environment')}|{entity.get('behavior', 'interacts')}"
            )
        else:
            entities.append(str(entity))
    return SpecDraft(
        title=str(spec.get("title") or "Game"),
        genre=str(spec.get("genre") or "Arcade"),
        objective=str(spec.get("objective") or ""),
        player_controls=ensure_string_list(spec.get("player_controls")),
        gameplay_loop=ensure_string_list(spec.get("gameplay_loop")),
        entities=entities,
        scoring_rules=ensure_string_list(spec.get("scoring_rules")),
        win_condition=str(spec.get("win_condition") or ""),
        lose_condition=str(spec.get("lose_condition") or ""),
    )


def generic_spec_from_hint(gameplay_brief: str) -> dict[str, Any]:
    draft = SpecDraft(
        title="Arcade Game",
        genre="Arcade",
        objective=gameplay_brief.strip() or "Build a playable keyboard-controlled canvas game.",
        player_controls=["keyboard controls described by the gameplay brief"],
        gameplay_loop=["start game", "control player", "resolve collisions", "update score", "show game over"],
        entities=[
            "player|player|main keyboard-controlled entity",
            "target|object|goal or item from the described game",
            "hazard|obstacle|failure condition or blocking object",
        ],
        scoring_rules=["score follows the described game objective"],
        win_condition="the described success condition is reached",
        lose_condition="the described failure condition is reached",
    )
    spec = expand_spec_draft(draft, gameplay_brief)
    spec["assumptions"] = [gameplay_brief.strip() or "Template fallback from gameplay brief"]
    spec["confidence_notes"] = ["Generic fallback used because the model did not return valid compact JSON"]
    return spec


# --- HTML processing ---

def prepare_full_html_output(raw_content: str) -> str:
    html = strip_code_fence(raw_content).strip()
    if "<!doctype" in html.lower():
        html = html[html.lower().find("<!doctype"):]
    elif "<html" in html.lower():
        html = html[html.lower().find("<html"):]
    return patch_iframe_keyboard(html)


def validate_html_game_output(html: str) -> None:
    lowered = html.lower()
    if len(html) < 200 or "<html" not in lowered or "<canvas" not in lowered:
        raise ValueError("The model did not return a complete canvas HTML game.")
    if "</html>" not in lowered:
        raise ValueError("Model output looks truncated (missing </html>).")
    if html_looks_corrupted(html):
        raise ValueError("Model HTML looks corrupted (broken tags or CSS).")


def html_looks_corrupted(html: str) -> bool:
    patterns = (
        r"<html\s*=",
        r";\s*dding\s*:",
        r"justify-content\s*:\s*;",
        r"<canvas\s+width=\"\d+\"\s*=\"",
    )
    return any(re.search(p, html, re.IGNORECASE) for p in patterns)


def strip_server_html_patch(html: str) -> str:
    while SERVER_HTML_PATCH_MARKER in html:
        marker_index = html.index(SERVER_HTML_PATCH_MARKER)
        script_start = html.rfind("<script", 0, marker_index)
        if script_start < 0:
            script_start = marker_index
        script_end = html.find("</script>", marker_index)
        if script_end < 0:
            break
        script_end += len("</script>")
        html = (html[:script_start] + html[script_end:]).strip()
    return html


def patch_iframe_keyboard(html: str) -> str:
    if SERVER_HTML_PATCH_MARKER in html:
        return html
    if "<canvas" in html and "tabindex=" not in html:
        html = html.replace("<canvas", '<canvas tabindex="0"', 1)

    patch = f"""
{SERVER_HTML_PATCH_MARKER}
<script>
(function () {{
  const canvas = document.querySelector("canvas");
  if (!canvas) return;
  if (!canvas.hasAttribute("tabindex")) canvas.setAttribute("tabindex", "0");
  function focusGame() {{ try {{ canvas.focus(); }} catch (e) {{}} }}
  window.addEventListener("load", focusGame);
  canvas.addEventListener("click", focusGame);
  document.querySelectorAll("button").forEach(b => b.addEventListener("click", () => setTimeout(focusGame, 50)));
  document.addEventListener("keydown", e => {{
    if (["ArrowUp","ArrowDown","ArrowLeft","ArrowRight"," "].includes(e.key)) e.preventDefault();
  }}, {{ passive: false }});
}})();
</script>
""".strip()

    if "</body>" in html:
        return html.replace("</body>", f"{patch}\n</body>")
    return f"{html}\n{patch}"


# --- Playwright validation ---

def validate_html_with_playwright(html: str, validation_seconds: int = 2) -> dict[str, Any]:
    try:
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
    except ImportError as error:
        raise ValueError("Playwright is not installed.") from error

    console_errors: list[str] = []
    page_errors: list[str] = []
    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except PlaywrightError as error:
            raise ValueError("Playwright Chromium not available.") from error
        try:
            page = browser.new_page(viewport={"width": 960, "height": 720})
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            page.set_content(html, wait_until="load", timeout=5000)

            if not page.locator("canvas").count():
                raise ValueError("HTML does not contain a canvas element.")

            clicked = False
            for sel in ("#startBtn", "#btn-start", "button:has-text('Start')", "button:has-text('开始')", "button"):
                loc = page.locator(sel).first
                if loc.count():
                    try:
                        loc.click(timeout=1000)
                        clicked = True
                        break
                    except PlaywrightError:
                        continue
            if not clicked:
                page.keyboard.press("Enter")
                page.keyboard.press("Space")

            page.wait_for_timeout(250)

            sample_js = """() => {
              const c = document.querySelector("canvas");
              if (!c) throw new Error("missing canvas");
              const ctx = c.getContext("2d");
              const d = ctx.getImageData(0, 0, c.width, c.height).data;
              const s = [];
              for (let y = 0; y < c.height; y += 18)
                for (let x = 0; x < c.width; x += 18) {
                  const i = (y * c.width + x) * 4;
                  s.push(d[i], d[i+1], d[i+2], d[i+3]);
                }
              return s;
            }"""
            before = page.evaluate(sample_js)
            page.keyboard.down("ArrowRight")
            page.wait_for_timeout(int(validation_seconds * 1000))
            page.keyboard.up("ArrowRight")
            after = page.evaluate(sample_js)

            motion_delta = sum(abs(int(a) - int(b)) for a, b in zip(before, after))

            canvas_stats = page.evaluate("""() => {
              const c = document.querySelector("canvas");
              if (!c) return {error: "missing canvas", changed: 0, total: 0};
              const ctx = c.getContext("2d");
              const d = ctx.getImageData(0, 0, c.width, c.height).data;
              let changed = 0, total = 0;
              for (let y = 0; y < c.height; y += 14)
                for (let x = 0; x < c.width; x += 14) {
                  const i = (y * c.width + x) * 4;
                  total++;
                  if (d[i+3] > 0 && (Math.abs(d[i]-31)>10 || Math.abs(d[i+1]-41)>10 || Math.abs(d[i+2]-55)>10))
                    changed++;
                }
              return {changed, total};
            }""")

            if canvas_stats.get("error"):
                raise ValueError(str(canvas_stats["error"]))
            if int(canvas_stats.get("changed") or 0) < 8:
                raise ValueError(f"Canvas appears blank after start: {canvas_stats}")
            if motion_delta < 500:
                raise ValueError(
                    "Canvas did not visibly change after start and ArrowRight input; "
                    "the game may be frozen or controls may be ineffective."
                )
            if page_errors:
                raise ValueError("Page errors: " + " | ".join(page_errors[:3]))
            if console_errors:
                raise ValueError("Console errors: " + " | ".join(console_errors[:3]))
            return {"canvas": canvas_stats, "motion_delta": motion_delta}
        finally:
            browser.close()
