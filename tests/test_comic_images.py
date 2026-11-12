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


@pytest.fixture(autouse=True)
def fake_ocr(monkeypatch):
    monkeypatch.setattr('comic_images.has_lettering',lambda data:False)
    monkeypatch.setattr('comic_images.remove_lettering',lambda data:data)

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


@pytest.mark.parametrize('status,count',[(400,1),(401,1),(429,1),(503,2)])
def test_provider_retry_only_transient_servers(monkeypatch,status,count):
    monkeypatch.setenv('CLOUDFLARE_API_TOKEN','test')
    monkeypatch.setenv('CLOUDFLARE_ACCOUNT_ID','a'*32)
    monkeypatch.setattr('providers.time.sleep',lambda seconds:None)
    calls=[]
    original=httpx.Client
    def handler(request):
        calls.append(request)
        return httpx.Response(status,json={'success':False,'errors':[{'code':3003,'message':'PRIVATE'}]})
    monkeypatch.setattr('providers.HTTPClient',lambda **kw:original(**kw,transport=httpx.MockTransport(handler)))
    with pytest.raises(ProviderError) as caught:
        ProviderRouter()._cloudflare_request('planning-model', {}, deadline=time.monotonic() + 60)
    assert len(calls)==count and 'PRIVATE' not in str(caught.value)
    assert '3003' in str(caught.value)


def test_failed_board_is_not_repeated_for_each_panel():
    class Router(FakeSceneRouter):
        count=0
        def _cloudflare_translate(self,text,**kw):return text
        def _cloudflare_image(self,*args,**kw):
            self.count+=1
            raise ProviderError('fixed safe error')
    router=Router();images=ComicImages(router)
    for i in range(4):
        with pytest.raises(ProviderError,match='fixed safe error'):images.panel(['scene']*4,i)
    assert router.count==1
    assert all('scene' not in key for key in images.failures)


def test_lettering_retries_each_requested_panel_once(monkeypatch):
    monkeypatch.setattr('comic_images.has_lettering',lambda data:True)
    class Router(FakeSceneRouter):
        count=0
        def _cloudflare_translate(self,text,**kw):return text
        def _cloudflare_image(self,*args,**kw):self.count+=1;return board()
    router=Router();images=ComicImages(router)
    assert [images.panel(['scene']*4,i) for i in range(4)]==[None]*4
    assert router.count==8


def test_lettering_recovery_returns_clean_second_board(monkeypatch):
    checks=iter([True,True]+[False]*8)
    monkeypatch.setattr('comic_images.has_lettering',lambda data:next(checks))
    class Router(FakeSceneRouter):
        count=0
        def _cloudflare_translate(self,text,**kw):return text
        def _cloudflare_image(self,*args,**kw):self.count+=1;return board()
    router=Router();assert ComicImages(router).panel(['scene']*4,0)
    assert router.count==2


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
