"""Cloudflare 전용 장면별 생성. API 필드는 바꾸지 않고 네 장면의 사물·행동을 검증한 뒤 각 그림을 반환합니다."""
import base64
import hashlib
import io
import json
import logging
import re
import threading
import time
from collections import OrderedDict

from PIL import Image
from engine import ProviderError
from image_quality import has_lettering, remove_lettering
from scene_prompting import scene_prompt
from comic_review import retry_hint


logger = logging.getLogger(__name__)

def visual_text(caption):
    """캡션은 원문 그대로 보존하고, 그림 입력에서만 직접 인용 대사를 제외합니다."""
    return re.sub(r'“[^”]*”|「[^」]*」|"[^"\n]*"', '', caption).strip()


class ComicImages:
    def __init__(self, router):
        self.router = router
        self.lock = threading.Lock()
        # 원문 대신 해시와 이미지 결과만 잠시 보관합니다. 디스크에는 저장하지 않습니다.
        self.cache = OrderedDict()
        self.failures = OrderedDict()
        self.ttl = 300.0
        self.max_bytes = 32_000_000

    def panel(self, captions, index):
        if len(captions) != 4 or not 0 <= index < 4:
            raise ProviderError('4컷 장면 구성을 다시 확인해 주세요.')
        key = hashlib.sha256(json.dumps(captions, ensure_ascii=False).encode()).hexdigest()
        deadline = time.monotonic() + 180
        if not self.lock.acquire(timeout=180):
            raise ProviderError('만화 생성 대기 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.', reason='timeout')
        try:
            now = time.monotonic()
            for old in list(self.failures):
                if now - self.failures[old][0] >= 15:
                    del self.failures[old]
            if key in self.failures:
                _, message = self.failures[key]
                raise ProviderError(message)

            for old in list(self.cache):
                if now - self.cache[old][0] >= self.ttl:
                    del self.cache[old]
            if key not in self.cache:
                specs = self.router._cloudflare_scene_specs(captions, deadline=deadline)
                while self.cache and len(self.cache) >= 4:
                    self.cache.popitem(last=False)
                # 장면 명세/결과는 짧은 메모리 캐시에만 보관합니다. API 필드 추가 없음.
                self.cache[key] = (time.monotonic(), [None] * 4, specs, [0.0] * 4)
            created, tiles, specs, attempted = self.cache[key]
            self.cache.move_to_end(key)
            if tiles[index] is not None:
                return tiles[index]
            if attempted[index] and time.monotonic() - attempted[index] < 15:
                return None  # 연속 클릭 방지; 15초 뒤 이 컷만 다시 생성합니다.
            scene = specs.scenes[index]
            prompt = scene_prompt(scene)
            reference = next((tile for tile in tiles if tile), None)
            for attempt in range(2):
                data = self.router._cloudflare_image(prompt, deadline=deadline)
                if time.monotonic() >= deadline:
                    raise ProviderError('만화 생성 시간이 초과되었습니다.', reason='timeout')
                lettering = has_lettering(data)
                if lettering:
                    data = remove_lettering(data)
                    lettering = has_lettering(data)
                failures = (['lettering'] if lettering else
                            self.router._cloudflare_review_scene(scene, data, captions,
                                reference=reference, deadline=deadline))
                if time.monotonic() >= deadline:
                    raise ProviderError('만화 품질 검사 시간이 초과되었습니다.', reason='timeout')
                if not failures:
                    tiles[index] = data
                    break
                # 고정 기준명만 기록하며 사용자 원문·그림·키는 기록하지 않습니다.
                logger.info('comic review_rejected panel=%d criteria=%s', index, ','.join(
                    name for name in failures if name in {'objects','action','appearance','grounding','lettering','composition','character'}))
                if attempt or deadline - time.monotonic() < 20:
                    break
                prompt = scene_prompt(scene) + ' ' + retry_hint(failures)
                if len(prompt) > 2048:
                    break
            attempted[index] = time.monotonic()
            size = sum(len(tile or '') for tile in tiles)
            if size > self.max_bytes:
                tiles[index] = None
                raise ProviderError('만화 이미지 용량이 너무 큽니다. 다시 시도해 주세요.')
            while len(self.cache) > 1 and sum(
                    sum(len(x or '') for x in item[1]) for item in self.cache.values()) > self.max_bytes:
                self.cache.popitem(last=False)
            return tiles[index]
        except ProviderError as error:
            # 실패한 합본을 나머지 컷 요청마다 재생성하지 않습니다. 예외 객체/원문은 보관하지 않습니다.
            if key not in self.failures:
                if len(self.failures) >= 4:
                    self.failures.popitem(last=False)
                self.failures[key] = (time.monotonic(), str(error))
            raise
        finally:
            self.lock.release()

    @staticmethod
    def _split(data):
        raw = base64.b64decode(data.split(',', 1)[1], validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            if image.width != image.height or image.width < 256 or image.width % 2:
                raise ProviderError('4컷 합본의 이미지 크기를 확인하지 못했습니다.')
            image.load()
            half = image.width // 2
            result = []
            for x, y in ((0, 0), (half, 0), (0, half), (half, half)):
                stream = io.BytesIO()
                image.crop((x, y, x + half, y + half)).convert('RGB').save(stream, format='PNG')
                result.append('data:image/png;base64,' + base64.b64encode(stream.getvalue()).decode())
            return result
