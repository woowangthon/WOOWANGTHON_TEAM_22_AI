"""그림책·4컷 만화의 BE↔AI 자료형. 기존 메시지 자료형과 독립적으로 추가합니다."""
from typing import Literal
from pydantic import Field, field_validator
from models import StrictModel


class VisualStoryRequest(StrictModel):
    diary_text: str = Field(min_length=1, max_length=6000)
    confirmed: bool = False  # BE가 사용자의 일기 원문 확인 상태를 관리합니다.
    format: Literal['storybook', 'comic4', 'both'] = 'both'
    storybook_pages: int = Field(default=4, ge=1, le=6)

    @field_validator('diary_text')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('확인한 일기가 필요합니다.')
        return value.strip()


class SceneGroup(StrictModel):
    source_ids: list[int]  # 모델은 새 문장을 쓰지 않고 원문 번호만 묶습니다.


class ScenePlan(StrictModel):
    scenes: list[SceneGroup]


class DiarySource(StrictModel):
    id: int  # 이 API가 나눈 일기 원문 조각의 번호입니다. 대화 메시지 ID가 아닙니다.
    text: str


class VisualScene(StrictModel):
    scene_id: str
    order: int
    caption: str  # 원문 조각을 그대로 연결한 글입니다.
    source_ids: list[int]
    imageUrl: str | None = None
    repeated: bool = False
    reuse_scene_id: str | None = None  # 같은 문장을 반복한 컷은 앞의 그림을 재사용합니다.


class VisualDocument(StrictModel):
    format: Literal['storybook', 'comic4']
    layout: Literal['pages', 'grid_2x2']
    planning_mode: Literal['model', 'deterministic', 'fallback', 'mock']
    scenes: list[VisualScene]
    notices: list[str]


class VisualStoryResponse(StrictModel):
    diary_text: str
    diary_hash: str
    sources: list[DiarySource]
    storybook: VisualDocument | None = None
    comic4: VisualDocument | None = None
    requires_confirmation: bool = True
    mock: bool


class VisualImageRequest(StrictModel):
    diary_text: str = Field(min_length=1, max_length=6000)
    diary_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    format: Literal['storybook', 'comic4']
    source_ids: list[int] = Field(min_length=1, max_length=80)
    confirmed: bool = False


class VisualImageResponse(StrictModel):
    diary_hash: str
    scene_key: str  # 일기·형식·근거가 같은지 BE가 비교하는 키입니다.
    caption: str
    source_ids: list[int]
    format: Literal['storybook', 'comic4']
    imageUrl: str | None
    status: Literal['generated', 'rejected', 'failed', 'mock']
    error: str | None = None
    requires_confirmation: bool = True
    mock: bool
