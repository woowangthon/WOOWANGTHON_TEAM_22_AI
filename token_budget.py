"""모델 전송 데이터만 압축합니다. 원문을 자르거나 요약하지 않습니다."""
def compact_payload(instruction, payload):
    conversation = payload.get('conversation')
    if not isinstance(conversation, list) or not all(isinstance(m, dict) and 'role' in m and 'text' in m for m in conversation):
        return instruction, payload
    data = dict(payload)
    data['conversation'] = [[i, m['role'], m['text']] for i, m in enumerate(conversation)]
    # sources는 conversation의 아이 발언과 완전히 같을 때만 제거합니다.
    sources = [{'id': i, 'text': m['text']} for i, m in enumerate(conversation) if m['role'] == 'child']
    if data.get('sources') == sources:
        del data['sources']
    return instruction + '\n입력 conversation의 각 행은 [원래 source_id, role, 원문]이다. sources가 생략되면 child 행이 sources다. assistant 행은 맥락일 뿐 사실 근거가 아니다.', data


def completion_budget(schema):
    # 추론 모델의 내부 토큰 여유도 남깁니다. 잘린 응답은 기존 오류 처리로 보냅니다.
    return {'QuestionCandidate': 768, 'Review': 512, 'DiaryCandidate': 2048, 'WorryAction': 512}.get(schema.__name__, 2048)
