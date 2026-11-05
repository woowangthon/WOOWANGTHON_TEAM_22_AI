"""[3] 대화와 일기 생성 로직. API 키를 프런트엔드에 전달하지 않습니다."""
import json
import os
from functools import cached_property
from openai import OpenAI
from models import QuestionCandidate, DiaryCandidate, Review
from prompts import CHAT_PROMPT, CHAT_REVIEW, DIARY_PROMPT, DIARY_REVIEW, IMAGE_PROMPT, IMAGE_REVIEW

class GenerationError(Exception):
    """키 누락·불완전 응답처럼 사용자에게 알려야 하는 오류입니다."""

class OpenAIAdapter:
    @cached_property
    def client(self):
        api_key = os.getenv('OPENAI_API_KEY')  # 서버 환경 변수에서만 키를 읽습니다.
        if not api_key:
            raise GenerationError('.env에 OPENAI_API_KEY를 설정한 뒤 서버를 다시 실행해 주세요.')
        return OpenAI(api_key=api_key, timeout=45, max_retries=0)

    def parse(self, instruction, payload, schema):
        response = self.client.responses.parse(
            model=os.getenv('TEXT_MODEL', 'gpt-4.1-mini'),
            input=[{'role':'system','content':instruction},
                   {'role':'user','content':json.dumps(payload, ensure_ascii=False)}],
            text_format=schema,
            store=False,  # 응답 저장 옵션. 계정의 ZDR 설정과는 별개입니다.
        )
        if response.output_parsed is None:
            raise GenerationError('AI가 응답을 완성하지 못했습니다. 다시 시도해 주세요.')
        return response.output_parsed

    def image(self, text):
        result = self.client.with_options(timeout=180).images.generate(
            model=os.getenv('IMAGE_MODEL','gpt-image-1.5'),
            prompt=IMAGE_PROMPT+'\n'+json.dumps({'confirmed_text':text}, ensure_ascii=False),
            size='1024x1024', quality='low', output_format='png', n=1,
        )
        if not result.data or not result.data[0].b64_json:
            raise GenerationError('이미지를 받지 못했습니다.')
        image_url = 'data:image/png;base64,'+result.data[0].b64_json
        response = self.client.responses.parse(
            model=os.getenv('TEXT_MODEL','gpt-4.1-mini'), store=False, text_format=Review,
            input=[{'role':'system','content':IMAGE_REVIEW}, {'role':'user','content':[
                {'type':'input_text','text':json.dumps({'confirmed_text':text},ensure_ascii=False)},
                {'type':'input_image','image_url':image_url}]}],
        )
        if response.output_parsed is None or not response.output_parsed.accepted:
            return None  # 자동 검토가 거절한 그림은 백엔드에 반환하지 않습니다.
        return image_url

class DiaryEngine:
    def __init__(self, adapter=None, mock=False):
        self.adapter = adapter or OpenAIAdapter()
        self.mock = mock  # 실제 AI 없이 백엔드와의 연결만 시험할 때 사용합니다.

    def conversation_data(self, messages):
        conversation = [message.model_dump() for message in messages]
        if sum(len(item['text']) for item in conversation)>20000:
            raise GenerationError('대화가 너무 길어요. 이번 이야기를 일기로 마무리해 주세요.')
        return conversation

    def next_question(self, messages):
        conversation = self.conversation_data(messages)
        child_messages = [item for item in conversation if item['role']=='child']
        if not child_messages:
            return {'question':'오늘은 무슨 일이 있었어?', 'finished':False, 'mock':self.mock}
        if self.mock:
            # 이 분기는 정해진 질문만 반환합니다. 실제 꼬리 질문은 아래 모델 호출에서 생성합니다.
            examples = ['그때 어떤 일이 있었는지 더 들려줄래?', '그때 어떤 기분이 들었어?', '더 남기고 싶은 이야기가 있어?']
            return {'question':examples[min(len(child_messages)-1,2)], 'finished':False, 'mock':True}
        candidate = self.adapter.parse(CHAT_PROMPT, {'conversation':conversation}, QuestionCandidate)
        review = self.adapter.parse(CHAT_REVIEW, {'conversation':conversation,'candidate':candidate.model_dump()}, Review)
        accepted = review.accepted and bool(candidate.question.strip()) and len(candidate.question)<=150
        return {'question':candidate.question if accepted else '더 들려주고 싶은 이야기가 있어?',
                'finished':candidate.finished if accepted else False, 'mock':False, 'fallback':not accepted}

    def make_diary(self, messages):
        conversation = self.conversation_data(messages)
        sources = [{'id':index,'text':item['text']} for index,item in enumerate(conversation) if item['role']=='child']
        if not sources:
            raise GenerationError('먼저 오늘 있었던 일을 한 문장 이상 이야기해 주세요.')
        fallback = self.mock  # 검사 실패 시 원문을 보여주며, 내용을 새로 만들어 채우지 않습니다.
        sentences = []
        if not self.mock:
            candidate = self.adapter.parse(DIARY_PROMPT, {'conversation':conversation,'sources':sources}, DiaryCandidate)
            allowed_ids = {source['id'] for source in sources}
            valid = 0<len(candidate.sentences)<=20 and all(
                sentence.text.strip() and len(sentence.text)<=500 and sentence.source_ids
                and set(sentence.source_ids)<=allowed_ids for sentence in candidate.sentences)
            if valid:
                review = self.adapter.parse(DIARY_REVIEW, {'conversation':conversation,'sources':sources,'candidate':candidate.model_dump()}, Review)
                valid = review.accepted
            fallback = not valid
            if valid:
                sentences = [sentence.model_dump() for sentence in candidate.sentences]
        if fallback:
            sentences = [{'text':source['text'],'source_ids':[source['id']]} for source in sources]
        page_size = max(1, (len(sentences)+5)//6)  # 최대 6페이지로 묶되 원문/문장을 버리지 않습니다.
        pages = []
        for start in range(0,len(sentences),page_size):
            group = sentences[start:start+page_size]
            pages.append({'text':'\n'.join(item['text'] for item in group),
                          'source_ids':sorted({sid for item in group for sid in item['source_ids']}), 'imageUrl':None})
        return {'text':'\n'.join(item['text'] for item in sentences), 'pages':pages, 'sources':sources,
                'fallback':fallback, 'requires_confirmation':True, 'mock':self.mock}
