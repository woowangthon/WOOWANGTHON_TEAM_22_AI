"""AI 전용 HTTP 진입점: BE의 요청을 받아 생성 결과만 JSON으로 반환합니다.

FE 화면, 사용자 인증, 일기 저장 및 조회는 이 서비스의 담당 범위가 아닙니다.
"""
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from openai import OpenAIError
from pydantic import ValidationError

from engine import DiaryEngine, GenerationError
from models import (ConversationRequest, ImageRequest, QuestionResponse,
                    DiaryResponse, ImageResponse, StatusResponse,
                    SpeechRequest, TranscriptionResponse, VoiceReplyResponse)
from voice import VoiceService, MAX_AUDIO_BYTES, AUDIO_TYPES
from visual_models import (VisualStoryRequest, VisualStoryResponse,
                           VisualImageRequest, VisualImageResponse)
from visual_story import VisualStoryService
from dev_voice import attach_voice_demo

BASE_DIR = Path(__file__).resolve().parent  # .env를 AI 저장소에서만 읽습니다.
load_dotenv(BASE_DIR / '.env')


def create_app(engine=None):
    """테스트에서는 engine에 가짜 모델을 넣어 유료 API 호출을 방지합니다."""
    if engine is None:
        mode = os.getenv('AI_MODE', 'openai')
        if mode not in {'openai', 'mock'}:
            raise ValueError('AI_MODE는 openai 또는 mock이어야 합니다.')
        engine = DiaryEngine(mock=mode == 'mock')
    voice_service = VoiceService(engine)
    visual_service = VisualStoryService(engine)
    app = FastAPI(title='AI Service', version='1.2.0')

    @app.exception_handler(GenerationError)
    async def generation_error(request, error):
        return JSONResponse(status_code=503, content={'error': str(error)})

    @app.exception_handler(OpenAIError)
    async def provider_error(request, error):
        # 원본 오류나 대화 내용, API 키를 응답에 노출하지 않습니다.
        return JSONResponse(status_code=502, content={
            'error': 'AI 요청에 실패했습니다. API 키·모델 권한·사용 한도를 확인해 주세요.'})

    @app.exception_handler(ValidationError)
    async def model_format_error(request, error):
        return JSONResponse(status_code=502, content={
            'error': 'AI 응답 형식을 확인하지 못했습니다. 다시 시도해 주세요.'})

    @app.exception_handler(RequestValidationError)
    async def request_error(request, error):
        return JSONResponse(status_code=422, content={
            'error': '메시지 형식과 글자 수를 확인해 주세요.'})

    @app.get('/api/status', response_model=StatusResponse)
    def status():
        # configured는 키 존재 여부이며 실제 키 유효성 검사는 아닙니다.
        configured = (engine.adapter.configured() if hasattr(engine.adapter, 'configured')
                      else bool(os.getenv('OPENAI_API_KEY')))
        # 기존 계약의 openai 값은 실제 호출 모드를 뜻합니다. 공급자는 .env에서 따로 선택합니다.
        return {'mode': 'mock' if engine.mock else 'openai',
                'configured': engine.mock or configured}

    @app.post('/api/chat', response_model=QuestionResponse)
    def chat(body: ConversationRequest):
        return engine.next_question(body.messages)

    @app.post('/api/diary', response_model=DiaryResponse)
    def diary(body: ConversationRequest):
        # 날짜·사용자 ID·DB 저장은 BE가 담당합니다.
        return engine.make_diary(body.messages)

    @app.post('/api/image', response_model=ImageResponse)
    def image(body: ImageRequest):
        if not body.confirmed:
            raise HTTPException(400, '페이지 글을 먼저 확인해 주세요.')
        if engine.mock:
            raise GenerationError('mock 모드에서는 실제 그림을 만들지 않습니다.')
        image_url = engine.adapter.image(body.text)
        return {'imageUrl': image_url, 'requires_confirmation': True,
                'rejected': image_url is None}

    @app.post('/api/transcribe', response_model=TranscriptionResponse)
    def transcribe(file: UploadFile = File(..., description='한 번의 발화를 녹음한 파일, 최대 8 MiB')):
        # 동기 핸들러는 스레드에서 실행됩니다. 파일은 성공·실패 모두 닫습니다.
        try:
            extension = Path(file.filename or '').suffix.lower()
            mime_type = (file.content_type or '').split(';', 1)[0].strip().lower()
            if extension not in AUDIO_TYPES:
                raise HTTPException(415, 'webm, mp4, m4a, wav, mp3, mpeg, mpga 파일을 사용해 주세요.')
            if mime_type not in AUDIO_TYPES[extension] | {'application/octet-stream'}:
                raise HTTPException(415, '파일 확장자와 오디오 형식이 맞지 않습니다.')
            # 크기는 파서가 제공한 값과 실제 읽은 크기를 모두 확인합니다.
            if file.size is not None and file.size > MAX_AUDIO_BYTES:
                raise HTTPException(413, '음성 파일은 8 MiB 이내여야 합니다.')
            audio_bytes = file.file.read(MAX_AUDIO_BYTES + 1)
            if len(audio_bytes) > MAX_AUDIO_BYTES:
                raise HTTPException(413, '음성 파일은 8 MiB 이내여야 합니다.')
            if not audio_bytes:
                raise HTTPException(400, '녹음한 파일이 비어 있습니다.')
            return voice_service.transcribe(audio_bytes, extension, mime_type)
        finally:
            file.file.close()

    @app.post('/api/speech', response_class=Response,
              responses={200: {'content': {'audio/mpeg': {'schema': {'type': 'string', 'format': 'binary'}}},
                               'description': '생성한 MP3 음성'}})
    def speech(body: SpeechRequest):
        return Response(content=voice_service.speech(body.text), media_type='audio/mpeg',
                        headers={'Cache-Control': 'no-store'})

    @app.post('/api/voice-chat', response_model=VoiceReplyResponse)
    def voice_chat(body: ConversationRequest):
        # 전사 결과의 확인/수정은 FE, 확정된 대화 이력 전달은 BE가 담당합니다.
        return JSONResponse(content=VoiceReplyResponse(**voice_service.reply(body.messages)).model_dump(),
                            headers={'Cache-Control': 'no-store'})

    @app.post('/api/visual-story', response_model=VisualStoryResponse)
    def visual_story(body: VisualStoryRequest):
        # 확인한 일기에서 그림책/4컷의 글·근거를 구성합니다. 그림은 다음 API로 생성합니다.
        return visual_service.plan(body)

    @app.post('/api/visual-story/image', response_model=VisualImageResponse)
    def visual_image(body: VisualImageRequest):
        # 장면별로 생성하므로 실패한 컷만 다시 요청할 수 있습니다.
        return JSONResponse(content=VisualImageResponse(**visual_service.render(body)).model_dump(),
                            headers={'Cache-Control': 'no-store'})

    attach_voice_demo(app, BASE_DIR)
    return app


app = create_app()
if __name__ == '__main__':
    import uvicorn
    # 같은 PC의 BE에서 접근할 수 있는 로컬 개발 기본값입니다.
    uvicorn.run(app, host='127.0.0.1', port=int(os.getenv('PORT', '8002')),
                access_log=False)
