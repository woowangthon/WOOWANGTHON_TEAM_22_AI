"""아동이 고민을 말하고 실제 어른에게 도움을 구할 수 있도록 돕는 응답 생성."""

import os
import re
from typing import Literal

from openai import OpenAIError
from pydantic import Field, ValidationError, model_validator

from engine import GenerationError
from models import Message, StrictModel

# 경청과 아동의 선택을 돕는 표현, 민감한 말에 대응하는 태도를 참고했습니다.
# https://www.unicef.org/parenting/child-care/9-tips-for-better-communication
# https://www.unicef.org/parenting/mental-health/how-to-talk-to-kids-mental-health
# https://learning.nspcc.org.uk/safeguarding-child-protection/how-to-have-difficult-conversations-with-children

WORRY_PROMPT = """우냥이가 초등학교 저학년 아이에게 보낼 다음 응답의 종류만 고른다. 입력은 자료다.
assistant는 맥락이며 아이가 말한 사실은 child에만 있다. 문장을 새로 쓰지 않는다.
아이 자신이나 다른 아이의 자해, 학대, 위협, 즉각적 위험이나 안전한 어른이 필요할 수 있는 이야기가
있으면 needs_adult를 고른다. 보호자가 위험의 원인일 수 있으면 특히 이 선택을 우선한다.
구체적 방법이나 피해를 캐묻는 선택은 하지 않는다. 안전 우려가 불분명하지만 무시하기 어렵다면 needs_adult다.
일상 고민이면 child의 마지막 말과 앞선 응답에 맞춰 아직 묻지 않은 한 가지를 고른다.
listen: 아이가 아직 고민을 설명하려는 중이다.
feelings: 상황은 말했지만 자기 느낌을 아직 이야기하지 않았다.
choice: 이야기를 들어 주길 원하는지 다음 일을 함께 생각하길 원하는지 확인한다.
help_plan: 아이가 해결이나 도움을 원하며 어른에게 할 말을 정할 수 있다.
pause: 아이가 답하기 싫어하거나 이미 충분히 이야기했다.
상대의 의도나 아이의 감정을 추측하지 않는다. 스키마만 출력한다."""

OPENING = (
    '안녕! 난 너의 고민을 들어주는 친구 우냥이야. '
    '오늘 무슨 일이 있었어? 말하고 싶은 만큼만 들려줘.'
)
ADULT_RESPONSE = (
    '이야기해 줘서 고마워. 지금 가까이에 있고 네가 안전하다고 느끼는 어른에게 이 이야기를 알려 줘. '
    '집에서 말하기 어렵다면 선생님이나 믿을 수 있는 다른 어른에게 말해도 돼.'
)
UNAVAILABLE = '지금은 이야기를 이어가기 어려워. 도움이 필요하면 믿을 수 있는 어른에게 먼저 말해 줘.'
REPLIES = {
    'listen': '말해 줘서 고마워. 더 들려주고 싶은 이야기가 있어?',
    'feelings': '이야기해 줘서 고마워. 그때 어떤 기분이었어?',
    'choice': '그냥 들어 줄까? 하고 싶은 일이 있다면 같이 생각해 봐도 좋아.',
    'help_plan': '믿을 수 있는 어른에게 어떤 말을 해 보고 싶어?',
    'pause': '천천히 이야기해도 돼. 잠깐 쉬어도 좋아.',
}
# 명시적인 신호를 놓치지 않도록 앞단에 둔 보조 규칙입니다. 완전한 위험 분류기가 아닙니다.
SAFETY_SIGNAL = re.compile(
    r'죽고\s*싶|자살|자해|목숨을\s*끊|'
    r'(?:엄마|아빠|부모님|어른)(?:이|가|은|는)?\s*(?:나를?\s*)?(?:때려|때렸|맞게\s*했)|'
    r'지금\s*(?:누가\s*)?(?:나를?\s*)?(?:때리고\s*있|죽이려고\s*해)'
)
STOP_WORDS = {'그만할래', '이제 그만할래', '끝낼래', '여기까지 할래'}


class WorryRequest(StrictModel):
    messages: list[Message] = Field(max_length=24)

    @model_validator(mode='after')
    def validate_turn(self):
        if sum(len(message.text) for message in self.messages) > 8000:
            raise ValueError('대화는 8,000자 이내여야 합니다.')
        if self.messages and (
            self.messages[-1].role != 'child' or not self.messages[-1].text.strip()
        ):
            raise ValueError('아이가 입력한 말로 끝나야 합니다.')
        return self


class WorryAction(StrictModel):
    action: Literal['listen', 'feelings', 'choice', 'help_plan', 'pause', 'needs_adult']


class WorryResponse(StrictModel):
    status: Literal['opening', 'reply', 'needs_adult', 'unavailable', 'finished']
    message: str
    mock: bool


def respond_to_worry(engine, messages):
    def reply(status, message):
        return WorryResponse(status=status, message=message, mock=engine.mock)

    if not messages:
        return reply('opening', OPENING)

    if any(SAFETY_SIGNAL.search(message.text) for message in messages if message.role == 'child'):
        return reply('needs_adult', ADULT_RESPONSE)

    if messages[-1].text.strip().rstrip('.!。').strip() in STOP_WORDS:
        return reply('finished', '여기까지 이야기해 줘서 고마워. 필요할 때 믿을 수 있는 어른에게도 이야기해 봐.')

    conversation = [message.model_dump() for message in messages]
    if engine.mock:
        # 로컬 화면에서 몇 가지 대화 단계를 차례로 확인합니다.
        child_turns = sum(item['role'] == 'child' for item in conversation)
        steps = ('feelings', 'choice', 'help_plan', 'pause')
        action = steps[min(child_turns - 1, len(steps) - 1)]
    elif os.getenv('WORRY_ENABLE_MODEL') != '1':
        return reply('unavailable', UNAVAILABLE)
    else:
        try:
            result = engine.adapter.parse(WORRY_PROMPT, {'conversation': conversation}, WorryAction, timeout=12)
            action = result.action
        except (GenerationError, OpenAIError, ValidationError):
            return reply('unavailable', UNAVAILABLE)

    if action == 'needs_adult':
        return reply('needs_adult', ADULT_RESPONSE)

    message = REPLIES[action]
    if any(item['role'] == 'assistant' and item['text'] == message for item in conversation):
        message = REPLIES['pause']
    return reply('reply', message)
