import base64
import json
import tempfile
from pathlib import Path
from typing import Any, List

import cv2
import ollama
import streamlit as st
import streamlit.components.v1 as components
from pydantic import BaseModel, Field, ValidationError, field_validator

OUTPUT_DIR = Path("outputs_local")
OUTPUT_DIR.mkdir(exist_ok=True)

DEFAULT_MODEL = "qwen3:8b"
STREAM_PREVIEW_LIMIT = 24_000
STREAM_UPDATE_CHARS = 160


def ensure_string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)]


class Entity(BaseModel):
    name: str
    role: str
    behavior: str


class Physics(BaseModel):
    gravity: str = ""
    jump_or_impulse: str = ""
    collision_style: str = ""
    movement_style: str = ""


class VisualStyle(BaseModel):
    perspective: str = ""
    palette: str = ""
    background: str = ""
    ui_elements: List[str] = Field(default_factory=list)

    @field_validator("ui_elements", mode="before")
    @classmethod
    def normalize_ui_elements(cls, value: Any) -> List[str]:
        return ensure_string_list(value)


class GameSpec(BaseModel):
    title: str
    genre: str
    objective: str
    player_controls: List[str]
    gameplay_loop: List[str]
    entities: List[Entity]
    scoring_rules: List[str]
    win_condition: str
    lose_condition: str
    physics: Physics
    visual_style: VisualStyle
    assumptions: List[str]
    confidence_notes: List[str]

    @field_validator(
        "player_controls",
        "gameplay_loop",
        "scoring_rules",
        "assumptions",
        "confidence_notes",
        mode="before",
    )
    @classmethod
    def normalize_string_lists(cls, value: Any) -> List[str]:
        return ensure_string_list(value)


SPEC_SYSTEM_PROMPT = """
You are a gameplay reverse-engineering analyst and minimalist arcade game designer.
You receive a handful of video frames and infer the smallest playable HTML5 game clone.
Only infer mechanics that are visible or strongly implied.
Prefer simple arcade mechanics such as Pong, Breakout, Snake, Flappy Bird, runner, or dodger games when evidence is incomplete.
Return strict JSON only. No markdown. No code fences.
""".strip()


CODE_SYSTEM_PROMPT = """
You are a senior JavaScript canvas game developer.
Generate a complete self-contained single-file HTML game.
Rules:
- Return raw HTML only.
- Use inline CSS and JavaScript.
- Use HTML5 canvas for gameplay.
- Use no external libraries, assets, CDNs, network calls, audio, or images.
- Include score, visible controls, start/restart support, and a clear game-over state.
- Use requestAnimationFrame.
- Make keyboard controls work in an iframe.
- The canvas must have tabindex="0".
- Automatically focus the canvas on load, click, start, and restart.
- Prevent default behavior for arrow keys and spacebar.
""".strip()


def model_dump(model: BaseModel) -> dict:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def response_content(chunk: Any) -> str:
    if isinstance(chunk, dict):
        return chunk.get("message", {}).get("content", "")
    message = getattr(chunk, "message", None)
    if isinstance(message, dict):
        return message.get("content", "")
    return getattr(message, "content", "") or ""


def preview_text(text: str) -> str:
    if len(text) <= STREAM_PREVIEW_LIMIT:
        return text
    return f"...仅显示最后 {STREAM_PREVIEW_LIMIT} 个字符...\n{text[-STREAM_PREVIEW_LIMIT:]}"


def stream_chat_content(
    *,
    model_name: str,
    messages: list[dict[str, Any]],
    options: dict[str, Any],
    placeholder: Any,
    language: str,
    response_format: str | None = None,
) -> str:
    content_parts = []
    shown_chars = 0
    kwargs: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "stream": True,
        "options": options,
    }
    if response_format:
        kwargs["format"] = response_format

    for chunk in ollama.chat(**kwargs):
        content = response_content(chunk)
        if not content:
            continue
        content_parts.append(content)

        full_content = "".join(content_parts)
        if len(full_content) - shown_chars >= STREAM_UPDATE_CHARS:
            placeholder.code(preview_text(full_content), language=language)
            shown_chars = len(full_content)

    full_content = "".join(content_parts)
    placeholder.code(preview_text(full_content), language=language)
    return full_content


def build_spec_prompt(game_hint: str, extra_constraints: str, max_frames: int) -> str:
    return f"""
Analyze the supplied still frames from a gameplay video and infer a minimal playable browser game.

Output valid JSON matching exactly this schema:
{{
  "title": "string",
  "genre": "string",
  "objective": "string",
  "player_controls": ["string"],
  "gameplay_loop": ["string"],
  "entities": [
    {{
      "name": "string",
      "role": "player|enemy|obstacle|projectile|ui|environment",
      "behavior": "string"
    }}
  ],
  "scoring_rules": ["string"],
  "win_condition": "string",
  "lose_condition": "string",
  "physics": {{
    "gravity": "string",
    "jump_or_impulse": "string",
    "collision_style": "string",
    "movement_style": "string"
  }},
  "visual_style": {{
    "perspective": "string",
    "palette": "string",
    "background": "string",
    "ui_elements": ["string"]
  }},
  "assumptions": ["string"],
  "confidence_notes": ["string"]
}}

Constraints:
- Keep the design implementable in one HTML file.
- Avoid menus, accounts, networking, cutscenes, assets, and multi-level progression.
- Prefer a playable small prototype over a complex clone.
- You are seeing at most {max_frames} frames, so be conservative.

Optional user hint:
{game_hint or "None"}

Extra constraints:
{extra_constraints or "None"}

Return JSON only.
""".strip()


def build_code_prompt(game_spec: dict) -> str:
    spec_json = json.dumps(game_spec, indent=2, ensure_ascii=False)
    return f"""
Generate a complete playable browser game from this specification:

{spec_json}

Implementation requirements:
- One self-contained HTML document.
- Inline CSS and JavaScript.
- Canvas-based game rendering.
- requestAnimationFrame game loop.
- Simple shapes and colors only.
- Visible score and instructions.
- Start and restart controls.
- Keyboard controls must work inside iframe previews.

Return raw HTML only.
""".strip()


def save_uploaded_video(uploaded_file) -> Path:
    suffix = Path(uploaded_file.name).suffix or ".mp4"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(uploaded_file.getbuffer())
        return Path(tmp.name)


def extract_frames(video_path: Path, max_frames: int) -> List[str]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError("Cannot open the uploaded video.")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if total_frames <= 0:
        total_frames = max_frames

    sample_indexes = {
        int(i * max(1, total_frames - 1) / max(1, max_frames - 1))
        for i in range(max_frames)
    }

    frames = []
    frame_index = 0
    while len(frames) < max_frames:
        ok, frame = cap.read()
        if not ok:
            break

        if frame_index in sample_indexes:
            ok, buffer = cv2.imencode(
                ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
            )
            if ok:
                frames.append(base64.b64encode(buffer).decode("ascii"))

        frame_index += 1

    cap.release()

    if not frames:
        raise ValueError("No frames could be extracted from the video.")
    return frames


def extract_json_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("The model did not return a JSON object.")
    return text[start : end + 1]


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


def patch_iframe_keyboard(html: str) -> str:
    if "<canvas" in html and "tabindex=" not in html:
        html = html.replace("<canvas", '<canvas tabindex="0"', 1)

    patch = """
<script>
(function () {
  const canvas = document.querySelector("canvas");
  if (!canvas) return;
  if (!canvas.hasAttribute("tabindex")) canvas.setAttribute("tabindex", "0");

  function focusGame() {
    try { canvas.focus(); } catch (error) {}
  }

  window.addEventListener("load", focusGame);
  canvas.addEventListener("click", focusGame);
  document.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => setTimeout(focusGame, 50));
  });
  document.addEventListener("keydown", (event) => {
    if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " "].includes(event.key)) {
      event.preventDefault();
    }
  }, { passive: false });
})();
</script>
""".strip()

    if "</body>" in html:
        return html.replace("</body>", f"{patch}\n</body>")
    return f"{html}\n{patch}"


def infer_game_spec(
    model_name: str,
    video_path: Path,
    game_hint: str,
    extra_constraints: str,
    max_frames: int,
    stream_placeholder: Any | None = None,
) -> dict:
    frames = extract_frames(video_path, max_frames)
    messages = [
        {"role": "system", "content": SPEC_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_spec_prompt(game_hint, extra_constraints, max_frames),
            "images": frames,
        },
    ]
    if stream_placeholder:
        raw_content = stream_chat_content(
            model_name=model_name,
            messages=messages,
            options={"temperature": 0.1, "num_ctx": 8192},
            placeholder=stream_placeholder,
            language="json",
            response_format="json",
        )
    else:
        response = ollama.chat(
            model=model_name,
            messages=messages,
            options={"temperature": 0.1, "num_ctx": 8192},
            format="json",
        )
        raw_content = response["message"]["content"]

    parsed = json.loads(extract_json_object(raw_content))
    return model_dump(GameSpec(**parsed))


def generate_game_html(
    model_name: str, game_spec: dict, stream_placeholder: Any | None = None
) -> str:
    messages = [
        {"role": "system", "content": CODE_SYSTEM_PROMPT},
        {"role": "user", "content": build_code_prompt(game_spec)},
    ]
    if stream_placeholder:
        raw_content = stream_chat_content(
            model_name=model_name,
            messages=messages,
            options={"temperature": 0.2, "num_ctx": 8192},
            placeholder=stream_placeholder,
            language="html",
        )
    else:
        response = ollama.chat(
            model=model_name,
            messages=messages,
            options={"temperature": 0.2, "num_ctx": 8192},
        )
        raw_content = response["message"]["content"]

    html = strip_code_fence(raw_content)
    if "<html" not in html.lower() or "<canvas" not in html.lower():
        raise ValueError("The model did not return a complete canvas HTML game.")
    return patch_iframe_keyboard(html)


def main() -> None:
    st.set_page_config(page_title="Video to playable HTML Game", layout="wide")
    st.title("Video to playable HTML Game")
    st.caption(
        "上传一段玩法视频，抽取关键帧，用 Ollama/Qwen 推断游戏规则并生成可玩的单文件 HTML5 游戏。"
    )

    with st.sidebar:
        st.header("生成设置")
        model_name = st.text_input("Ollama 模型", value=DEFAULT_MODEL)
        max_frames = st.slider("抽帧数量", min_value=3, max_value=8, value=5)
        game_hint = st.text_input("玩法提示", value="Simple Snake-like arcade game")
        extra_constraints = st.text_area(
            "额外约束",
            value="Keep the game simple, responsive, and playable with arrow keys or spacebar.",
            height=120,
        )

    uploaded_video = st.file_uploader(
        "上传游戏视频",
        type=["mp4", "mov", "avi", "mkv", "webm"],
    )

    st.session_state.setdefault("game_spec", None)
    st.session_state.setdefault("game_html", None)

    if uploaded_video is None:
        st.info("请先上传一段较短的玩法视频。首次运行前需要执行：ollama run qwen3:8b")
        return

    video_path = save_uploaded_video(uploaded_video)
    left, right = st.columns([1, 1])

    with left:
        st.subheader("原始视频")
        st.video(str(video_path))

    with right:
        st.subheader("本地生成流水线")
        if st.button("生成 HTML 游戏", type="primary"):
            status_placeholder = st.empty()
            with st.expander("模型中间输出：游戏规格 JSON", expanded=True):
                spec_stream_placeholder = st.empty()
            with st.expander("模型中间输出：HTML 源码", expanded=True):
                html_stream_placeholder = st.empty()

            try:
                status_placeholder.info("正在抽帧并推断游戏规格...")
                spec = infer_game_spec(
                    model_name=model_name,
                    video_path=video_path,
                    game_hint=game_hint,
                    extra_constraints=extra_constraints,
                    max_frames=max_frames,
                    stream_placeholder=spec_stream_placeholder,
                )
                st.session_state.game_spec = spec

                status_placeholder.info("正在根据规格生成单文件 HTML 游戏...")
                html = generate_game_html(
                    model_name,
                    st.session_state.game_spec,
                    stream_placeholder=html_stream_placeholder,
                )
                st.session_state.game_html = html
                html_stream_placeholder.code(preview_text(html), language="html")
                (OUTPUT_DIR / "game_spec.json").write_text(
                    json.dumps(
                        st.session_state.game_spec, indent=2, ensure_ascii=False
                    ),
                    encoding="utf-8",
                )
                (OUTPUT_DIR / "generated_game.html").write_text(html, encoding="utf-8")

                status_placeholder.success("生成完成。")
            except ValidationError as error:
                status_placeholder.error(f"规格校验失败：{error}")
            except Exception as error:
                status_placeholder.error(f"生成失败：{error}")

    if st.session_state.game_spec:
        st.subheader("推断出的游戏规格")
        st.json(st.session_state.game_spec)

    if st.session_state.game_html:
        preview_tab, code_tab, download_tab = st.tabs(["预览", "HTML 源码", "下载"])
        with preview_tab:
            st.caption("点击游戏区域后使用键盘操作。如果焦点丢失，再点击一次画布即可。")
            components.html(st.session_state.game_html, height=760, scrolling=False)
        with code_tab:
            st.code(st.session_state.game_html, language="html")
        with download_tab:
            st.download_button(
                "下载 HTML 游戏",
                data=st.session_state.game_html,
                file_name="generated_game.html",
                mime="text/html",
            )
            st.download_button(
                "下载游戏规格 JSON",
                data=json.dumps(
                    st.session_state.game_spec, indent=2, ensure_ascii=False
                ),
                file_name="game_spec.json",
                mime="application/json",
            )


if __name__ == "__main__":
    main()
