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
from dataclasses import dataclass, field

from PIL import Image
from engine import ProviderError
from image_quality import has_lettering, remove_lettering
from scene_prompting import SceneSpecs, scene_prompt


logger = logging.getLogger(__name__)

def visual_text(caption):
    """캡션은 원문 그대로 보존하고, 그림 입력에서만 직접 인용 대사를 제외합니다."""
    return re.sub(r'“[^”]*”|「[^」]*」|"[^"\n]*"', '', caption).strip()


# Cloudflare 요금표를 바탕으로 한 계획용 예약치이며 실제 청구량과는 다릅니다.
COMIC_NEURON_BUDGET = 2500
PLAN_NEURON_RESERVE = 600
PANEL_NEURON_RESERVE = 300  # FLUX 이미지와 시각 검토를 함께 예약합니다.


@dataclass
class ComicRun:
    created_at: float
    panel_count: int
    specs: SceneSpecs | None = None
    tiles: list[str | None] = field(default_factory=lambda: [None] * 4)
    attempted: set[int] = field(default_factory=set)
    rejected_at: dict[int, float] = field(default_factory=dict)
    uncertain: dict[int, int] = field(default_factory=dict)
    reserved_neurons: int = 0

    def reserve(self, amount, *, preserve_first_pass):
        untried = self.panel_count - len(self.attempted)
        first_pass = untried * PANEL_NEURON_RESERVE if preserve_first_pass else 0
        if self.reserved_neurons + amount + first_pass > COMIC_NEURON_BUDGET:
            raise ProviderError('이 만화의 생성 예산을 모두 사용했어요. 완성된 컷과 일기 글은 남아 있어요.')
        self.reserved_neurons += amount


class ComicImages:
    def __init__(self, router):
        self.router = router
        self.lock = threading.Lock()
        # 장면 명세와 이미지 결과는 짧게 메모리에만 보관합니다.
        self.cache = OrderedDict()
        self.failures = OrderedDict()
        self.ttl = 300.0
        self.max_bytes = 32_000_000

    def panel(self, captions, index, *, panel_count=4):
        if len(captions) != 4 or not 0 <= index < panel_count <= 4:
            raise ProviderError('4컷 장면 구성을 다시 확인해 주세요.')
        key = hashlib.sha256(json.dumps([panel_count, captions], ensure_ascii=False).encode()).hexdigest()
        panel_key = (key, index)
        shared_key = (key, None)
        failure_key = shared_key
        deadline = time.monotonic() + 180
        if not self.lock.acquire(timeout=180):
            raise ProviderError('만화 생성 대기 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.', reason='timeout')
        try:
            now = time.monotonic()
            for old in list(self.failures):
                if now - self.failures[old][0] >= 15:
                    del self.failures[old]
            for old in list(self.cache):
                if now - self.cache[old].created_at >= self.ttl:
                    del self.cache[old]
            cached = self.cache.get(key)
            if cached is not None and cached.tiles[index] is not None:
                self.cache.move_to_end(key)
                return cached.tiles[index]

            for cached_key in (shared_key, panel_key):
                if cached_key in self.failures:
                    failure_key = cached_key
                    _, message, reason, status, provider = self.failures[cached_key]
                    raise ProviderError(message, reason=reason, status_code=status, provider=provider)

            if cached is not None and index in cached.uncertain:
                failure_key = panel_key
                raise ProviderError('이 컷의 이전 생성 결과를 확인하지 못했습니다.',
                                    reason='image_result_unknown', status_code=cached.uncertain[index])

            if cached is None:
                while len(self.cache) >= 4:
                    self.cache.popitem(last=False)
                cached = self.cache[key] = ComicRun(time.monotonic(), panel_count)
            self.cache.move_to_end(key)
            if cached.specs is None:
                cached.specs = self._plan_scenes(captions, deadline, cached)

            failure_key = panel_key
            tiles, specs = cached.tiles, cached.specs
            retrying = index in cached.attempted
            if retrying:
                rejected_at = cached.rejected_at.get(index)
                if rejected_at is None:
                    raise ProviderError('이 컷의 이전 요청 상태를 확인해 주세요.')
                if len(cached.attempted) < panel_count or time.monotonic() - rejected_at < 15:
                    return None
            cached.reserve(PANEL_NEURON_RESERVE, preserve_first_pass=retrying)
            cached.attempted.add(index)
            if not retrying:
                cached.created_at = time.monotonic()
            cached.rejected_at.pop(index, None)
            scene = specs.scenes[index]
            prompt = scene_prompt(scene)
            reference = next((tile for tile in tiles if tile), None)
            data = self.router._cloudflare_image(prompt, deadline=deadline)
            if time.monotonic() >= deadline:
                raise ProviderError('만화 생성 시간이 초과되었습니다.', reason='timeout')
            lettering = has_lettering(data)
            if lettering:
                cleaned = remove_lettering(data)
                if cleaned != data:
                    data = cleaned
                    lettering = has_lettering(data)
            failures = (['lettering'] if lettering else
                        self.router._cloudflare_review_scene(scene, data, captions,
                            reference=reference, deadline=deadline))
            if time.monotonic() >= deadline:
                raise ProviderError('만화 품질 검사 시간이 초과되었습니다.', reason='timeout')
            if failures:
                # 기준명만 기록하고, 이 요청에서는 같은 컷을 다시 생성하지 않습니다.
                logger.info('comic review_rejected panel=%d criteria=%s', index, ','.join(
                    name for name in failures if name in {'objects','action','appearance','grounding','lettering','composition','character'}))
                cached.rejected_at[index] = time.monotonic()
            else:
                tiles[index] = data

            size = sum(len(tile or '') for tile in tiles)
            if size > self.max_bytes:
                tiles[index] = None
                raise ProviderError('만화 이미지 용량이 너무 큽니다. 다시 시도해 주세요.')
            while len(self.cache) > 1 and sum(
                    sum(len(x or '') for x in item.tiles) for item in self.cache.values()) > self.max_bytes:
                self.cache.popitem(last=False)
            return tiles[index]
        except ProviderError as error:
            if failure_key == panel_key and cached is not None and index in cached.attempted:
                if error.reason in {'timeout', 'image_result_unknown'} or error.status_code == 504:
                    cached.uncertain[index] = error.status_code or (504 if error.reason == 'timeout' else 502)
            # 장면 계획이나 계정 공통 오류는 전체에 적용하고, 개별 컷 오류는 해당 컷에만 적용합니다.
            if error.status_code in {401, 403, 429} or error.reason in {'quota_exhausted', 'rate_limit'}:
                failure_key = shared_key
            if failure_key not in self.failures:
                if len(self.failures) >= 20:
                    self.failures.popitem(last=False)
                self.failures[failure_key] = (time.monotonic(), str(error), error.reason,
                                              error.status_code, error.provider)
            raise
        finally:
            self.lock.release()

    def _plan_scenes(self, captions, deadline, run):
        # 계획 재작성에만 추가 호출을 허용합니다. 두 번 모두 같은 총 시간 예산을 사용합니다.
        plan_deadline = min(deadline, time.monotonic() + 55)
        run.reserve(PLAN_NEURON_RESERVE, preserve_first_pass=True)
        try:
            return self.router._cloudflare_scene_specs(captions, deadline=plan_deadline)
        except ProviderError as error:
            if error.reason != 'response_schema_invalid' or plan_deadline - time.monotonic() < 8:
                raise
        run.reserve(PLAN_NEURON_RESERVE, preserve_first_pass=True)
        return self.router._cloudflare_scene_specs(captions, deadline=plan_deadline, repair=True)

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
