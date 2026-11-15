"""느린 OCR 중에도 생성 원본과 공급자 호출 횟수를 보존합니다."""
from concurrent.futures import ThreadPoolExecutor
import threading

from comic_images import ComicImages
from engine import ProviderError
from test_comic_images import FakeSceneRouter, board


def test_slow_ocr_does_not_hold_generation_lock_or_duplicate_calls(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    class Router(FakeSceneRouter):
        def _cloudflare_image(self, prompt, **kwargs):
            calls.append(prompt)
            return board()

    images = ComicImages(Router())

    def cleanup(data):
        assert not images.lock.locked()
        if threading.current_thread().name.startswith('first'):
            entered.set()
            assert release.wait(5)
        return data

    monkeypatch.setattr('comic_images.remove_lettering', cleanup)
    with ThreadPoolExecutor(1, thread_name_prefix='first') as pool:
        pending = pool.submit(images.panel, ['합성 종이배'] * 4, 0)
        try:
            assert entered.wait(2)
            assert images.panel(['합성 종이배'] * 4, 0) == board()
            assert len(calls) == 1
            assert images.panel(['합성 종이배'] * 4, 1) == board()
            assert len(calls) == 2
        finally:
            release.set()
        assert pending.result(2) == board()


def test_cached_original_survives_failed_cleanup_without_regeneration(monkeypatch):
    calls = []

    class Router(FakeSceneRouter):
        def _cloudflare_image(self, prompt, **kwargs):
            calls.append(prompt)
            return board()

    images = ComicImages(Router())

    def unavailable(data):
        raise ProviderError('synthetic OCR failure')

    monkeypatch.setattr('comic_images.remove_lettering', unavailable)
    assert images.panel(['합성'] * 4, 0) == board()
    monkeypatch.setattr('comic_images.remove_lettering', lambda data: data)
    assert images.panel(['합성'] * 4, 0) == board()
    assert len(calls) == 1
