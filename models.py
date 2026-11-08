"""[1] 백엔드에서 받는 요청과 AI 응답의 자료형을 정의합니다."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')  # 문서에 없는 필드는 거절합니다.

class Message(StrictModel):
    role: Literal['child', 'assistant']  # 아이의 말과 AI의 질문을 구분합니다.
    text: str = Field(min_length=1, max_length=2000)

class ConversationRequest(StrictModel):
    messages: list[Message] = Field(default_factory=list, max_length=60)

class QuestionCandidate(StrictModel):
    question: str  # 짧은 반응과 한 개의 후속 질문입니다.
    finished: bool  # 아이가 종료 의사를 표현했을 때 true입니다.

class Sentence(StrictModel):
    text: str  # 일기로 다듬은 한 문장입니다.
    source_ids: list[int]  # 근거가 되는 아이 발언의 번호입니다.

class DiaryCandidate(StrictModel):
    sentences: list[Sentence]

class Review(StrictModel):
    accepted: bool  # 생성 결과를 그대로 보여줘도 되는지에 대한 보조 검사입니다.

class ImageRequest(StrictModel):
    text: str = Field(min_length=1, max_length=1500)  # 사용자가 확인한 페이지 문장입니다.
    confirmed: bool = False  # 확인 전 이미지 생성을 막습니다.

# 아래 응답 모델은 BE 개발자가 /docs에서 실제 응답 구조를 확인하도록 정의합니다.
class StatusResponse(StrictModel):
    mode: Literal['openai', 'mock']
    configured: bool

class QuestionResponse(StrictModel):
    question: str
    finished: bool
    mock: bool
    fallback: bool = False

class Source(StrictModel):
    id: int  # 요청 messages 배열 내 위치(0부터)입니다. DB ID가 아닙니다.
    text: str

class Page(StrictModel):
    text: str  # 그림책 장면용 생성 콘텐츠이며 화면 레이아웃은 아닙니다.
    source_ids: list[int]
    imageUrl: str | None = None  # 이미지 생성은 별도 요청으로 수행합니다.

class DiaryResponse(StrictModel):
    text: str
    pages: list[Page]
    sources: list[Source]
    fallback: bool
    requires_confirmation: bool
    mock: bool

class ImageResponse(StrictModel):
    imageUrl: str | None  # PNG/JPEG 데이터 URL. 영구 저장 URL은 BE가 생성합니다.
    requires_confirmation: bool
    rejected: bool

class SpeechRequest(StrictModel):
    text: str = Field(min_length=1, max_length=1000)  # 읽을 확정 문장입니다.

    @field_validator('text')
    @classmethod
    def not_blank(cls, value):
        if not value.strip():
            raise ValueError('읽을 문장이 필요합니다.')
        return value.strip()

class TranscriptionResponse(StrictModel):
    text: str  # 인식한 원문 초안. 확인 후에만 대화에 추가합니다.
    requires_confirmation: bool = True
    mock: bool = False

class VoiceReplyResponse(QuestionResponse):
    audio_base64: str | None = None  # MP3 바이너리의 base64 표현입니다.
    audio_mime_type: str | None = None
    audio_error: str | None = None  # 음성만 실패하면 question은 그대로 반환합니다.
