"""Cloudflare 전용 장면별 생성. API 필드는 바꾸지 않고 네 장면의 사물·행동을 검증한 뒤 각 그림을 반환합니다."""
import base64
import hashlib
import io
import json
import re
import threading
import time
from collections import OrderedDict

from PIL import Image
from engine import ProviderError
from image_quality import has_lettering, remove_lettering
from scene_prompting import scene_prompt
from comic_review import retry_hint



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
                # 원문 인용은 검사용으로만 사용하고 이미지 프롬프트에는 보내지 않습니다.
                specs = self.router._cloudflare_scene_specs(captions, deadline=deadline)
                # 합본 실험에서 사건이 섞여, 각 요청에는 한 장면만 전달합니다.
                # 네 장면을 모두 마친 결과만 캐시하여 부분 생성 결과가 완료로 표시되지 않게 합니다.
                tiles = []
                retry_left = 1
                for scene in specs.scenes:
                    prompt = scene_prompt(scene)
                    clean = None
                    while True:
                        data = self.router._cloudflare_image(prompt, deadline=deadline)
                        if time.monotonic() >= deadline:
                            raise ProviderError('만화 생성 시간이 초과되었습니다.', reason='timeout')
                        if has_lettering(data):
                            data = remove_lettering(data)
                        failures = (['lettering'] if has_lettering(data) else
                                    self.router._cloudflare_review_scene(scene, data, captions,
                                        reference=tiles[0] if tiles else None, deadline=deadline))
                        if time.monotonic() >= deadline:
                            raise ProviderError('만화 품질 검사 시간이 초과되었습니다.', reason='timeout')
                        if not failures:
                            clean = data
                            break
                        if retry_left <= 0 or deadline - time.monotonic() < 20:
                            break
                        retry_left -= 1
                        prompt = scene_prompt(scene) + ' ' + retry_hint(failures)
                        if len(prompt) > 2048:
                            break
                    if clean is None:
                        tiles = [None] * 4
                        break
                    tiles.append(clean)
                size = sum(len(tile or '') for tile in tiles)
                if size > self.max_bytes:
                    raise ProviderError('만화 이미지 용량이 너무 큽니다. 다시 시도해 주세요.')
                while self.cache and (len(self.cache) >= 4 or
                        sum(sum(len(x or '') for x in item[1]) for item in self.cache.values()) + size > self.max_bytes):
                    self.cache.popitem(last=False)
                self.cache[key] = (time.monotonic(), tiles)
            self.cache.move_to_end(key)
            return self.cache[key][1][index]
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
