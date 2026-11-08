"""음성 인식(STT)과 음성 합성(TTS). 마이크 장치 제어는 FE에서 담당합니다."""
import base64

from prompts import TTS_INSTRUCTIONS
import os

from openai import OpenAIError

from engine import GenerationError

# 한 번의 발화에 대한 파일 제한입니다. 업로드 전체 크기 제한은 BE/프록시에도 적용합니다.
MAX_AUDIO_BYTES = 8 * 1024 * 1024
AUDIO_TYPES = {
    '.webm': {'audio/webm', 'video/webm'},
    '.mp4': {'audio/mp4', 'video/mp4', 'audio/x-m4a'},
    '.m4a': {'audio/mp4', 'audio/m4a', 'audio/x-m4a', 'video/mp4'},
    '.wav': {'audio/wav', 'audio/x-wav', 'audio/wave'},
    '.mp3': {'audio/mpeg', 'audio/mp3'},
    '.mpeg': {'audio/mpeg', 'video/mpeg'},
    '.mpga': {'audio/mpeg'},
}


class VoiceService:
    def __init__(self, engine):
        self.engine = engine  # 텍스트 질문 생성 로직을 공유합니다.

    def require_live_mode(self):
        if self.engine.mock:
            raise GenerationError('mock 모드에서는 음성 인식·합성을 수행하지 않습니다. AI_MODE=openai와 API 키를 설정해 주세요.')

    def transcribe(self, audio_bytes, extension, mime_type):
        """음성을 원문 언어로 전사합니다. 일기 정리/감정 추론은 수행하지 않습니다."""
        self.require_live_mode()
        if hasattr(self.engine.adapter, 'transcribe'):
            transcript = self.engine.adapter.transcribe(audio_bytes, extension, mime_type).strip()
        else:
            transcript = self._legacy_transcribe(audio_bytes, extension, mime_type)
        if not transcript:
            raise GenerationError('말소리를 인식하지 못했습니다. 다시 녹음하거나 글로 입력해 주세요.')
        if len(transcript) > 2000:
            raise GenerationError('인식한 글이 2,000자를 넘습니다. 더 짧게 나누어 녹음해 주세요.')
        return {'text': transcript, 'requires_confirmation': True, 'mock': False}

    def _legacy_transcribe(self, audio_bytes, extension, mime_type):
        result = self.engine.adapter.client.with_options(timeout=60).audio.transcriptions.create(
            model=os.getenv('STT_MODEL', 'gpt-transcribe'),
            # 사용자가 지정한 파일명 대신 정해진 이름으로 전달합니다.
            file=('recording' + extension, audio_bytes, mime_type),
        )
        return (result.text or '').strip()

    def speech(self, text):
        """주어진 문장만 MP3로 읽습니다. 출력은 AI 서버에 영구 저장하지 않습니다."""
        self.require_live_mode()
        if hasattr(self.engine.adapter, 'speech'):
            audio_bytes = self.engine.adapter.speech(text)
            if not audio_bytes:
                raise GenerationError('음성 응답을 받지 못했습니다.')
            return audio_bytes
        with self.engine.adapter.client.with_options(timeout=60).audio.speech.with_streaming_response.create(
            model=os.getenv('TTS_MODEL', 'gpt-4o-mini-tts'),
            voice=os.getenv('TTS_VOICE', 'coral'),
            input=text,
            response_format='mp3',
            instructions=TTS_INSTRUCTIONS,
        ) as response:
            audio_bytes = response.read()
        if not audio_bytes:
            raise GenerationError('음성 응답을 받지 못했습니다. 글로 확인하거나 음성만 다시 요청해 주세요.')
        return audio_bytes

    def reply(self, messages):
        """검사된 질문을 생성한 뒤 읽습니다. TTS 실패 시에도 생성한 질문을 보존합니다."""
        question_result = self.engine.next_question(messages)
        result = {**question_result, 'audio_base64': None, 'audio_mime_type': None,
                  'audio_error': None}
        if self.engine.mock:
            result['audio_error'] = 'mock 모드: 고정 질문만 반환하며 실제 음성은 없습니다.'
            return result
        try:
            audio_bytes = self.speech(question_result['question'])
            result['audio_base64'] = base64.b64encode(audio_bytes).decode('ascii')
            result['audio_mime_type'] = 'audio/mpeg'
        except GenerationError as error:
            result['audio_error'] = str(error)
        except OpenAIError:
            # 텍스트 생성까지 다시 요청하면 중복 질문/비용이 발생하므로 음성만 재시도합니다.
            result['audio_error'] = '질문은 생성했지만 음성 합성에 실패했습니다. 글로 표시하고 /api/speech로 음성만 재시도해 주세요.'
        return result
