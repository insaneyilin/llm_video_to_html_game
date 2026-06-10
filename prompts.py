import json
from typing import Any

HINT_SYSTEM_PROMPT = """
You analyze gameplay screenshots and write a short gameplay brief for building a simple HTML5 arcade prototype.
Return JSON only: {"gameplay_brief": "..."}.
Write gameplay_brief in Chinese unless the user notes ask for another language.
Keep gameplay_brief to 2-4 short sentences covering genre, controls, goal, and lose condition.
Boldly simplify to a standard arcade pattern; do not copy every UI detail from screenshots.
No markdown, no code fences, no bullet lists inside the string.
""".strip()

SPEC_DRAFT_SYSTEM_PROMPT = """
Convert a gameplay brief into a compact JSON draft for an HTML5 arcade game.
Return JSON only with exactly these keys:
title, genre, objective, player_controls, gameplay_loop, entities, scoring_rules, win_condition, lose_condition

Rules:
- player_controls, gameplay_loop, scoring_rules are arrays of short strings
- entities is an array of 3-5 strings formatted as "name|role|behavior"
  Example: "paddle|player|moves left and right at the bottom"
- Keep every string short. No nested objects. No markdown.
""".strip()

SPEC_EDIT_SYSTEM_PROMPT = """
Edit a compact GameSpec draft per user request.
Return JSON only with exactly these keys:
title, genre, objective, player_controls, gameplay_loop, entities, scoring_rules, win_condition, lose_condition

Rules:
- player_controls, gameplay_loop, scoring_rules are arrays of short strings
- entities is an array of strings formatted as "name|role|behavior"
- Keep every string short. No nested objects. No markdown.
""".strip()

FULL_HTML_SYSTEM_PROMPT = """
You are a senior HTML5 canvas game developer.
Generate one complete self-contained single-file HTML game from the GameSpec.

Return raw HTML only. No markdown or code fences.
Requirements:
- Include <!doctype html>, html/head/body, inline CSS, inline JavaScript.
- Use one canvas for gameplay.
- No external libraries, images, audio, network calls, or imports.
- Include visible score/status, start/restart behavior, and game over or win state.
- Keyboard controls must work in an iframe: canvas tabindex, focus on load/click/start, prevent arrow/space scrolling.
- The game must be playable, moving, and responsive after start.
- Keep the implementation simple and robust rather than visually perfect.
- Keep the file compact. Prefer one clean implementation over decorative UI, long comments, menus, levels, assets, or extra features.
- Avoid verbose explanations inside comments. Do not include analysis, planning text, debug logs, or repeated alternative implementations.
- Finish the document completely. The final characters of your response must be </html>.
- If you are running out of space, simplify gameplay immediately and close </script>, </body>, and </html> before adding anything else.
""".strip()

HTML_EDIT_SYSTEM_PROMPT = """
You fix bugs in an existing single-file HTML5 canvas game.
Return the complete updated HTML document only. No markdown, code fences, or partial diffs.
Keep inline CSS/JS, canvas rendering, requestAnimationFrame loop, and iframe-friendly keyboard controls.
Fix the user's reported issues without rewriting unrelated working code.
Preserve gameplay intent from the supplied hint unless the user asks to change behavior.
""".strip()


def build_hint_prompt(max_frames: int, user_notes: str = "") -> str:
    notes_section = ""
    if user_notes.strip():
        notes_section = f"\nOptional user notes:\n{user_notes.strip()}\n\n"
    return f"""
Look at the gameplay screenshots and write one gameplay brief for the next step.

You are seeing at most {max_frames} frames.
{notes_section}Return JSON only:
{{"gameplay_brief": "..."}}
""".strip()


def build_spec_prompt(gameplay_brief: str, extra_constraints: str) -> str:
    return f"""
Gameplay brief:
{gameplay_brief.strip()}

Extra constraints:
{extra_constraints or "None"}

Example output shape:
{{
  "title": "Brick Breaker",
  "genre": "Breakout",
  "objective": "Clear all bricks with the ball.",
  "player_controls": ["left arrow", "right arrow"],
  "gameplay_loop": ["move paddle", "bounce ball", "break bricks", "track score"],
  "entities": [
    "paddle|player|moves horizontally at the bottom",
    "ball|projectile|bounces off paddle, walls, and bricks",
    "brick|obstacle|breaks when hit by the ball"
  ],
  "scoring_rules": ["+10 per brick"],
  "win_condition": "all bricks destroyed",
  "lose_condition": "ball falls off the bottom with no lives left"
}}

Return JSON only.
""".strip()


def build_spec_edit_prompt(current_draft_json: str, user_message: str) -> str:
    return f"""
Current compact draft:
{current_draft_json}

Change request:
{user_message.strip()}

Return ONLY the updated compact JSON draft with the same keys.
""".strip()


def build_full_html_prompt(game_spec: dict[str, Any]) -> str:
    spec_json = json.dumps(game_spec, indent=2, ensure_ascii=False)
    return f"""
GameSpec:
{spec_json}

Create the complete single-file HTML game now.

Hard output constraints:
- Return only one compact HTML document.
- Target less than 900 lines and less than 45 KB.
- Do not include comments longer than one short line.
- Do not add optional features beyond the GameSpec.
- End the response exactly with </html>.
""".strip()


def build_html_edit_prompt(current_html: str, user_message: str, gameplay_hint: str = "") -> str:
    hint_section = gameplay_hint.strip() or "Not provided. Infer intended gameplay from the HTML."
    return f"""
Gameplay intent:
{hint_section}

Current HTML game:
{current_html}

Fix request:
{user_message}

Return the full fixed HTML document only.
""".strip()
