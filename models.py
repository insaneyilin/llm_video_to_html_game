from typing import Any, List

from pydantic import BaseModel, Field, field_validator


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


class GameplayHint(BaseModel):
    gameplay_brief: str = Field(min_length=20, max_length=600)


class SpecDraft(BaseModel):
    title: str
    genre: str
    objective: str
    player_controls: List[str]
    gameplay_loop: List[str]
    entities: List[str]
    scoring_rules: List[str]
    win_condition: str
    lose_condition: str

    @field_validator("player_controls", "gameplay_loop", "entities", "scoring_rules", mode="before")
    @classmethod
    def normalize_lists(cls, value: Any) -> List[str]:
        return ensure_string_list(value)


# --- Request models ---

class ExtractRequest(BaseModel):
    max_frames: int = Field(6, ge=3, le=12)


class HintRequest(BaseModel):
    model: str = "qwen3.5:9b"
    max_frames: int = Field(6, ge=3, le=12)
    user_notes: str = ""


class SpecRequest(BaseModel):
    model: str = "qwen3.5:9b"
    game_hint: str = ""
    extra_constraints: str = (
        "Keep the game simple, responsive, and playable with arrow keys or spacebar."
    )
    max_frames: int = Field(6, ge=3, le=12)


class SpecEditRequest(BaseModel):
    model: str = "qwen3.5:9b"
    current_spec: dict[str, Any]
    user_message: str


class HtmlRequest(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek-v4-pro"
    game_spec: dict[str, Any]


class HtmlEditRequest(BaseModel):
    provider: str = "deepseek"
    model: str = "deepseek-v4-pro"
    current_html: str
    gameplay_hint: str = ""
    user_message: str
