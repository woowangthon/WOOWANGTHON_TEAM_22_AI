"""실제 모델을 호출하지 않는 합본 자르기·원문 보존·동시 요청 회귀 검사."""
import base64
import io
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from PIL import Image

from comic_images import ComicImages, visual_text
from engine import ProviderError
from providers import ProviderRouter


class FakeSceneRouter:
    def _cloudflare_review_scene(self,*args,**kw):return []
    def _cloudflare_scene_specs(self,captions,**kw):
        from scene_prompting import validate_specs
        return validate_specs({'scenes':[{
            'index':i,'source_quote':caption,'objects':[{'name':'blocks','source_quote':caption}],
            'action':'The narrator stacks blocks.','action_quote':caption,'mode':'actual'
        } for i,caption in enumerate(captions)]},captions)


def board():
    picture=Image.new('RGB',(512,512))
    for box,color in zip([(0,0,256,256),(256,0,512,256),(0,256,256,512),(256,256,512,512)],
                         ['red','green','blue','yellow']):picture.paste(color,box)
    output=io.BytesIO();picture.save(output,format='PNG')
    return 'data:image/png;base64,'+base64.b64encode(output.getvalue()).decode()


def test_split_preserves_order_and_pixels():
    tiles=ComicImages._split(board())
    for tile,color in zip(tiles,[(255,0,0),(0,128,0),(0,0,255),(255,255,0)]):
        image=Image.open(io.BytesIO(base64.b64decode(tile.split(',')[1])))
        assert image.size==(256,256) and image.getpixel((128,128))==color


def test_concurrent_panels_generate_once_and_keep_dialogue_out_of_prompt():
    calls=[]
    class Router(FakeSceneRouter):
        def _cloudflare_translate(self,text,**kw):
            assert '대사' not in text
            return text
        def _cloudflare_image(self,prompt,**kw):
            calls.append(prompt)
            return ComicImages._split(board())[len(calls)-1]
    images=ComicImages(Router())
    captions=['블록을 쌓으며 “대사”라고 말했다.']*4
    with ThreadPoolExecutor(4) as pool:
        results=list(pool.map(lambda index:images.panel(captions,index),range(4)))
    assert len(calls)==4 and len(set(results))==4
    assert 'cream bean mascot' in calls[0]
    assert '대사' not in calls[0]
    assert captions[0]=='블록을 쌓으며 “대사”라고 말했다.'


def test_prompt_overflow_fails_without_silent_truncation():
    class Router(FakeSceneRouter):
        def _cloudflare_scene_specs(self,captions,**kw):
            plan=super()._cloudflare_scene_specs(captions,**kw)
            from scene_prompting import ObjectSpec
            for scene in plan.scenes:
                scene.action='a'*2100
                scene.objects=[ObjectSpec(name='a'*65,source_quote=captions[0])]*4
            return plan
        def _cloudflare_image(self,*args,**kw):raise AssertionError('must not call image')
    with pytest.raises(ProviderError,match='한도'):
        ComicImages(Router()).panel(['긴 장면']*4,0)


def test_expired_board_regenerates(monkeypatch):
    class Router(FakeSceneRouter):
        count=0
        def _cloudflare_translate(self,text,**kw):return 'blocks'
        def _cloudflare_image(self,*args,**kw):self.count+=1;return board()
    router=Router();images=ComicImages(router);images.ttl=0
    images.panel(['블록']*4,0);images.panel(['블록']*4,0)
    assert router.count==2


@pytest.mark.parametrize('http_status', [200, 500, 502, 503, 504])
def test_render_comic_settings_limit_image_and_http_attempts(monkeypatch, http_status):
    monkeypatch.setenv('CLOUDFLARE_API_TOKEN', 'test')
    monkeypatch.setenv('CLOUDFLARE_ACCOUNT_ID', 'a' * 32)
    monkeypatch.setenv('CLOUDFLARE_IMAGE_MODEL', '@cf/black-forest-labs/flux-1-schnell')
    image_calls = []
    http_calls = []
    image = board()

    def handle_image(request):
        http_calls.append(request)
        return httpx.Response(http_status, json={
            'success': http_status == 200,
            'result': {'image': image.split(',', 1)[1]},
        })

    transport = httpx.MockTransport(handle_image)
    monkeypatch.setattr('providers.HTTPClient', lambda **options: httpx.Client(
        transport=transport, **options,
    ))

    class RenderComicImagesStub:
        def __init__(self, router):
            self.router = router

        def generate_rejected_panel(self):
            # The reported legacy caller falls back to two attempts when the attribute is missing.
            for _ in range(getattr(self.router, 'comic_image_attempts', 2)):
                image_calls.append('synthetic scene')
                self.router._cloudflare_image(image_calls[-1])
                # The synthetic quality check rejects every generated image.

    router = ProviderRouter(comic_image_attempts=1, cloudflare_http_attempts=1)
    comic = RenderComicImagesStub(router)
    if http_status == 200:
        comic.generate_rejected_panel()
    else:
        with pytest.raises(ProviderError) as error:
            comic.generate_rejected_panel()
        assert error.value.reason == 'image_result_unknown'
        assert error.value.status_code == http_status

    assert len(image_calls) == len(http_calls) == 1
    assert router.cloudflare_http_attempts == 1


@pytest.mark.parametrize('status', [400, 401, 429, 500, 502, 503, 504])
@pytest.mark.parametrize('router_options', [{}, {'comic_image_attempts': 1, 'cloudflare_http_attempts': 1}])
def test_cloudflare_json_is_sent_once(monkeypatch, status, router_options):
    monkeypatch.setenv('CLOUDFLARE_API_TOKEN','test')
    monkeypatch.setenv('CLOUDFLARE_ACCOUNT_ID','a'*32)
    calls=[]
    original=httpx.Client
    def handler(request):
        calls.append(request)
        return httpx.Response(status,json={'success':False,'errors':[{'code':3003,'message':'PRIVATE'}]})
    monkeypatch.setattr('providers.HTTPClient',lambda **kw:original(**kw,transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as caught:
        ProviderRouter(**router_options)._cloudflare_request('planning-model', {}, deadline=time.monotonic() + 60)
    assert len(calls) == 1
    assert caught.value.status_code == status
    assert 'PRIVATE' not in str(caught.value)
    assert '3003' in str(caught.value)


def test_account_quota_failure_is_not_repeated_for_each_panel():
    class Router(FakeSceneRouter):
        count=0
        def _cloudflare_translate(self,text,**kw):return text
        def _cloudflare_image(self,*args,**kw):
            self.count+=1
            raise ProviderError('fixed safe error', reason='quota_exhausted', status_code=429)
    router=Router();images=ComicImages(router)
    for i in range(4):
        with pytest.raises(ProviderError,match='fixed safe error'):images.panel(['scene']*4,i)
    assert router.count==1
    assert all('scene' not in digest and index is None for digest, index in images.failures)


def test_generated_panels_are_returned_without_visual_review():
    class Router(FakeSceneRouter):
        calls = 0

        def _cloudflare_image(self, *args, **kwargs):
            self.calls += 1
            return board()

        def _cloudflare_review_scene(self, *args, **kwargs):
            pytest.fail('Generated comic panels should skip visual review')

    router = Router()
    images = ComicImages(router)
    captions = ['장면'] * 4
    assert [images.panel(captions, index) for index in range(4)] == [board()] * 4
    assert images.panel(captions, 0) == board()
    assert router.calls == 4


def test_ocr_failure_is_not_passed(monkeypatch):
    from image_quality import has_lettering
    monkeypatch.setattr('image_quality._ocr_engine',lambda: (_ for _ in ()).throw(RuntimeError('PRIVATE')))
    with pytest.raises(ProviderError) as error:has_lettering(board())
    assert 'PRIVATE' not in str(error.value)


def test_safety_rejection_never_retries_or_leaks_source(monkeypatch):
    monkeypatch.setenv('CLOUDFLARE_API_TOKEN','test')
    monkeypatch.setenv('CLOUDFLARE_ACCOUNT_ID','a'*32)
    calls=[];original=httpx.Client
    def handler(request):
        calls.append(request)
        return httpx.Response(400,json={'errors':[{'code':8007,'message':'Input prompt contains NSFW content. PRIVATE'}]})
    monkeypatch.setattr('providers.HTTPClient',lambda **kw:original(**kw,transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as caught:ProviderRouter()._cloudflare_image('synthetic')
    assert caught.value.reason=='response_filtered' and len(calls)==1
    assert 'PRIVATE' not in str(caught.value)


def test_text_removal_preserves_pixels_outside_mask(monkeypatch):
    from types import SimpleNamespace
    import numpy as np
    from image_quality import remove_lettering
    detected=SimpleNamespace(txts=['ABC'],scores=[0.99],boxes=[[[10,10],[40,10],[40,20],[10,20]]])
    monkeypatch.setattr('image_quality._ocr_engine',lambda:lambda pixels:detected)
    data=board()
    before=np.array(Image.open(io.BytesIO(base64.b64decode(data.split(',')[1]))))
    clean=remove_lettering(data)
    after=np.array(Image.open(io.BytesIO(base64.b64decode(clean.split(',')[1]))))
    assert np.array_equal(before[30:,:,:],after[30:,:,:])


def test_large_text_mask_never_erases_illustration(monkeypatch):
    from types import SimpleNamespace
    from image_quality import remove_lettering
    detected=SimpleNamespace(txts=['ABC'],scores=[0.99],boxes=[[[0,0],[500,0],[500,500],[0,500]]])
    monkeypatch.setattr('image_quality._ocr_engine',lambda:lambda pixels:detected)
    data=board()
    assert remove_lettering(data)==data


@pytest.mark.parametrize('code', [4006, 3036])
def test_cloudflare_daily_quota_reports_reset_without_retry(monkeypatch, code):
    monkeypatch.setenv('CLOUDFLARE_API_TOKEN', 'test')
    monkeypatch.setenv('CLOUDFLARE_ACCOUNT_ID', 'a' * 32)
    calls = []
    original = httpx.Client

    def handler(request):
        calls.append(request)
        return httpx.Response(429, json={'success': False, 'errors': [{'code': code}]})

    monkeypatch.setattr('providers.HTTPClient', lambda **kw: original(
        **kw, transport=httpx.MockTransport(handler)
    ))
    with pytest.raises(ProviderError, match='오전 9시') as caught:
        ProviderRouter()._cloudflare_image('test')
    assert caught.value.reason == 'quota_exhausted'
    assert len(calls) == 1


@pytest.mark.parametrize('status', [502, 503, 504])
def test_image_gateway_failure_never_resends_generation(monkeypatch, status):
    monkeypatch.setenv('CLOUDFLARE_API_TOKEN', 'test')
    monkeypatch.setenv('CLOUDFLARE_ACCOUNT_ID', 'a' * 32)
    calls = []
    original = httpx.Client

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={'success': False})

    monkeypatch.setattr('providers.HTTPClient', lambda **kw: original(
        **kw, transport=httpx.MockTransport(handler)
    ))
    with pytest.raises(ProviderError) as caught:
        ProviderRouter()._cloudflare_image('test')
    assert caught.value.reason == 'image_result_unknown'
    assert caught.value.status_code == status
    assert len(calls) == 1


def test_panel_error_cache_preserves_unknown_result():
    class Router(FakeSceneRouter):
        calls = 0

        def _cloudflare_image(self, *args, **kwargs):
            self.calls += 1
            raise ProviderError('fixed error', reason='image_result_unknown',
                                status_code=504, provider='cloudflare')

    router = Router()
    images = ComicImages(router)
    for _ in range(2):
        with pytest.raises(ProviderError) as caught:
            images.panel(['장면'] * 4, 0)
        assert caught.value.reason == 'image_result_unknown'
        assert caught.value.status_code == 504
    assert router.calls == 1


def test_cached_success_is_accessible_after_a_later_panel_fails():
    class Router(FakeSceneRouter):
        calls = 0

        def _cloudflare_image(self, *args, **kwargs):
            self.calls += 1
            if self.calls > 1:
                raise ProviderError('fixed error', reason='image_result_unknown', status_code=504)
            return board()

    router = Router()
    images = ComicImages(router)
    captions = ['장면'] * 4
    first = images.panel(captions, 0)
    with pytest.raises(ProviderError):
        images.panel(captions, 1)
    assert images.panel(captions, 0) == first
    assert router.calls == 2


def test_uncertain_panel_does_not_block_other_panels_or_resend_itself():
    class Router(FakeSceneRouter):
        calls = 0
        plan_calls = 0

        def _cloudflare_scene_specs(self, *args, **kwargs):
            self.plan_calls += 1
            return super()._cloudflare_scene_specs(*args, **kwargs)

        def _cloudflare_image(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ProviderError('result unknown', reason='image_result_unknown', status_code=504)
            return board()

    router = Router()
    images = ComicImages(router)
    captions = ['장면'] * 4
    with pytest.raises(ProviderError, match='result unknown'):
        images.panel(captions, 0)
    assert all(images.panel(captions, index) for index in (1, 2, 3))
    with pytest.raises(ProviderError, match='result unknown'):
        images.panel(captions, 0)
    assert router.calls == 4
    assert router.plan_calls == 1


def test_invalid_scene_plan_repairs_before_any_image_request():
    class Router(FakeSceneRouter):
        attempts = []
        images = 0

        def _cloudflare_scene_specs(self, captions, *, deadline, repair=False):
            self.attempts.append((deadline, repair))
            assert self.images == 0
            if not repair:
                raise ProviderError('invalid plan', reason='response_schema_invalid')
            return super()._cloudflare_scene_specs(captions, deadline=deadline)

        def _cloudflare_image(self, *args, **kwargs):
            self.images += 1
            return board()

    router = Router()
    assert ComicImages(router).panel(['장면'] * 4, 0)
    assert [repair for _, repair in router.attempts] == [False, True]
    assert router.attempts[0][0] == router.attempts[1][0]
    assert router.images == 1


def test_plan_budget_preserves_all_four_first_image_calls():
    from comic_images import ComicRun, PANEL_NEURON_RESERVE, PLAN_NEURON_RESERVE

    run = ComicRun(created_at=100.0, panel_count=4)
    run.reserve(PLAN_NEURON_RESERVE, preserve_first_pass=True)
    run.reserve(PLAN_NEURON_RESERVE, preserve_first_pass=True)
    with pytest.raises(ProviderError, match='생성 예산'):
        run.reserve(PLAN_NEURON_RESERVE, preserve_first_pass=True)
    for _ in range(4):
        run.reserve(PANEL_NEURON_RESERVE, preserve_first_pass=False)
    assert run.reserved_neurons == 2500


def test_unknown_panel_stays_blocked_after_short_failure_cache_expires(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr('comic_images.time.monotonic', lambda: clock[0])

    class Router(FakeSceneRouter):
        calls = 0

        def _cloudflare_image(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise ProviderError('result unknown', reason='image_result_unknown', status_code=504)
            return board()

    router = Router()
    images = ComicImages(router)
    captions = ['장면'] * 4
    with pytest.raises(ProviderError):
        images.panel(captions, 0)
    clock[0] += 16
    with pytest.raises(ProviderError) as error:
        images.panel(captions, 0)
    assert error.value.reason == 'image_result_unknown'
    assert images.panel(captions, 1)
    assert router.calls == 2


def test_text_cleanup_preserves_panel_if_local_ocr_fails(monkeypatch):
    class Router(FakeSceneRouter):
        def _cloudflare_image(self, *args, **kwargs):
            return board()

    def unavailable(_):
        raise ProviderError('private OCR details')

    monkeypatch.setattr('comic_images.remove_lettering', unavailable)
    images = ComicImages(Router())
    assert images.panel(['장면'] * 4, 0) == board()


def test_malformed_shared_plan_falls_back_to_each_original_caption(monkeypatch):
    monkeypatch.setattr('comic_images.remove_lettering', lambda data: data)

    class Router(FakeSceneRouter):
        plans = 0
        prompts = []

        def _cloudflare_scene_specs(self, *args, **kwargs):
            self.plans += 1
            raise ProviderError('invalid scene JSON', reason='response_schema_invalid')

        def _cloudflare_image(self, prompt, **kwargs):
            self.prompts.append(prompt)
            if '첫 장면' in prompt:
                raise ProviderError('safety filter', reason='response_filtered', status_code=400)
            return board()

    captions = ['첫 장면', '둘째 장면', '셋째 장면', '넷째 장면']
    router = Router()
    images = ComicImages(router)
    with pytest.raises(ProviderError, match='safety filter'):
        images.panel(captions, 0)
    for index in (1, 2, 3):
        assert images.panel(captions, index) == board()
    assert images.panel(captions, 1) == board()
    assert router.plans == 2
    assert len(router.prompts) == 4
    for caption, prompt in zip(captions, router.prompts):
        assert all((other in prompt) == (other == caption) for other in captions)


def test_scene_timeout_uses_direct_caption_with_short_image_budget(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr('comic_images.time.monotonic', lambda: clock[0])
    monkeypatch.setattr('comic_images.remove_lettering', lambda data: data)

    class Router(FakeSceneRouter):
        def _cloudflare_scene_specs(self, captions, *, deadline):
            assert deadline == 120.0
            clock[0] = deadline
            raise ProviderError('scene timeout', reason='timeout', status_code=504)

        def _cloudflare_image(self, prompt, *, deadline, steps):
            assert '첫 장면' in prompt and '둘째 장면' not in prompt
            assert deadline == 200.0
            assert steps == 4
            return board()

    assert ComicImages(Router()).panel(['첫 장면', '둘째 장면', '셋째 장면', '넷째 장면'], 0) == board()


def test_valid_image_is_returned_when_generation_uses_entire_budget(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr('comic_images.time.monotonic', lambda: clock[0])
    monkeypatch.setattr('comic_images.remove_lettering', lambda _: pytest.fail('no time for OCR'))

    class Router(FakeSceneRouter):
        def _cloudflare_image(self, prompt, *, deadline, steps):
            clock[0] = deadline + 1
            return board()

    assert ComicImages(Router()).panel(['장면'] * 4, 0) == board()
