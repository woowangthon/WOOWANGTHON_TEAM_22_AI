"""Synthetic API checks. --live explicitly enables billed provider calls.
Run from repository root; artifacts contain synthetic inputs only, never credentials.
"""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from engine import DiaryEngine
from server import create_app
from models import DiaryResponse, QuestionResponse
from providers import setting


def verify_diary(body, messages):
    DiaryResponse.model_validate(body)
    assert set(body) == set(DiaryResponse.model_fields)
    sources = [{'id': i, 'text': m['text']} for i, m in enumerate(messages) if m['role'] == 'child']
    assert body['sources'] == sources
    allowed = {s['id'] for s in sources}
    assert 1 <= len(body['pages']) <= 6
    assert body['requires_confirmation'] is True
    for page in body['pages']:
        assert page['imageUrl'] is None
        assert page['source_ids'] and set(page['source_ids']) <= allowed
    assert body['text'].split() == ' '.join(p['text'] for p in body['pages']).split()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--smoke', action='store_true', help='Only explicit finish and simple diary')
    parser.add_argument('--images', action='store_true', help='Also render four unique scenes and one legacy image')
    parser.add_argument('--output', required=True)
    parser.add_argument('--interval', type=float, default=0, help='Seconds between requests; avoids burst limits')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    report = {'timestamp': datetime.now(timezone.utc).isoformat(), 'mode': 'live' if args.live else 'mock',
              'branch': subprocess.check_output(['git', 'branch', '--show-current'], text=True).strip(),
              'head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
              'settings': {k: setting(k, default) for k, default in {
                  'TEXT_PROVIDER': 'groq', 'GROQ_TEXT_MODEL': 'openai/gpt-oss-20b',
                  'IMAGE_PROVIDER': 'cloudflare', 'CLOUDFLARE_IMAGE_MODEL': '@cf/black-forest-labs/flux-1-schnell',
                  'VISION_PROVIDER': 'groq', 'GROQ_VISION_MODEL': 'qwen/qwen3.8-27b'}.items()}, 'calls': []}
    def save():
        (out / 'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    with TestClient(create_app(DiaryEngine(mock=not args.live))) as client:
        def call(name, path, request):
            if report['calls'] and args.interval:
                time.sleep(args.interval)
            start = time.perf_counter()
            response = client.post(path, json=request)
            entry = {'name': name, 'path': path, 'request': request, 'http_status': response.status_code,
                     'seconds': round(time.perf_counter() - start, 3), 'response': response.json()}
            body = entry['response']
            if body.get('imageUrl'):
                from PIL import Image
                import io
                header, encoded = body['imageUrl'].split(',', 1)
                raw = base64.b64decode(encoded, validate=True)
                with Image.open(io.BytesIO(raw)) as picture:
                    picture.load()
                    entry['image'] = {'format': picture.format, 'width': picture.width, 'height': picture.height, 'bytes': len(raw)}
                    assert header == f'data:image/{"jpeg" if picture.format == "JPEG" else "png"};base64'
                    (out / (name + ('.jpg' if picture.format == 'JPEG' else '.png'))).write_bytes(raw)
            report['calls'].append(entry)
            save()
            print(name, response.status_code, body.get('status', ''), entry['seconds'], flush=True)
            if response.status_code == 200:
                if path == '/api/chat':
                    QuestionResponse.model_validate(body)
                    assert set(body) == set(QuestionResponse.model_fields)
                elif path == '/api/diary':
                    verify_diary(body, request['messages'])
            return body
        if args.smoke:
            call('explicit_finish', '/api/chat', {'messages': [{'role': 'child', 'text': '이제 그만할래. 일기로 만들어 줘.'}]})
            call('simple_diary', '/api/diary', {'messages': [
                {'role': 'assistant', 'text': '오늘 무슨 일이 있었어?'},
                {'role': 'child', 'text': '집에서 파란 블록을 쌓았어.'},
                {'role': 'assistant', 'text': '어떤 기분이 들었어?'},
                {'role': 'child', 'text': '재미있었어.'}]})
            return
        messages = [{'role': 'assistant', 'text': '오늘 무슨 일이 있었어?'}]
        for name, answer in [('followup', '친구랑 공원에서 공놀이 했어.'),
                             ('short', '응'), ('correction', '아니, 공원이 아니라 집이었어. 공놀이는 안 했고 블록을 쌓았어.'),
                             ('refusal', '기분은 말하기 싫어.'), ('finish', '이제 그만할래. 일기로 만들어 줘.')]:
            messages.append({'role': 'child', 'text': answer})
            body = call(name, '/api/chat', {'messages': list(messages)})
            if 'question' in body:
                messages.append({'role': 'assistant', 'text': body['question']})
        call('diary', '/api/diary', {'messages': messages})
        text = '빨간 공을 굴렸다. 파란 블록을 쌓았다. 종이에 동그라미를 그렸다. 책을 펼쳤다. 책을 덮었다.'
        plan = call('plan', '/api/visual-story', {'diary_text': text, 'format': 'comic4', 'confirmed': True})
        assert len(plan['comic4']['scenes']) == 4
        assert plan['comic4']['layout'] == 'grid_2x2'
        short = call('short_plan', '/api/visual-story', {'diary_text': '블록을 쌓았다.', 'format': 'comic4', 'confirmed': True})
        assert all(s['reuse_scene_id'] == 'comic4-1' for s in short['comic4']['scenes'][1:])
        if args.images:
            for scene in plan['comic4']['scenes']:
                call(scene['scene_id'], '/api/visual-story/image', {
                    'diary_text': plan['diary_text'], 'diary_hash': plan['diary_hash'],
                    'source_ids': scene['source_ids'], 'format': 'comic4', 'confirmed': True})
            call('legacy_image', '/api/image', {'text': '빨간 공을 굴렸다.', 'confirmed': True})
    save()

if __name__ == '__main__':
    main()
