"""불일치·불완전 검사를 성공으로 처리하지 않는지 검사합니다. 외부 호출 없음."""
import pytest
from comic_review import parse_checks,retry_hint
from engine import ProviderError
from scene_prompting import SceneSpec
from test_comic_images import FakeSceneRouter, board
from comic_images import ComicImages


def scene():
    return SceneSpec(index=0,source_quote='공을 들었다.',objects=[{'name':'ball','source_quote':'공'}],
                     action='The narrator holds a ball.',action_quote='공을 들었다.',mode='actual')

def checks(**overrides):
    return {**{k:True for k in ('objects','action','appearance','grounding','lettering','composition','character')},
            'object_counts':[1],**overrides}

def test_duplicate_main_prop_is_rejected_even_if_model_votes_pass():
    assert parse_checks(checks(object_counts=[2]),scene())==['objects']

def test_action_and_color_mismatches_are_rejected():
    assert parse_checks(checks(action=False,appearance=False),scene())==['action','appearance']

@pytest.mark.parametrize('value',[{},checks(action='true'),checks(object_counts=[]),checks(object_counts=[True])])
def test_incomplete_or_non_boolean_review_is_failed(value):
    with pytest.raises(ProviderError):parse_checks(value,scene())

def test_quality_rejection_retries_once_and_never_caches_unchecked_images(monkeypatch):
    monkeypatch.setattr('comic_images.has_lettering',lambda data:False)
    class Router(FakeSceneRouter):
        images=0
        def _cloudflare_image(self,*a,**kw):self.images+=1;return board()
        def _cloudflare_review_scene(self,*a,**kw):return ['action']
    router=Router();images=ComicImages(router)
    assert [images.panel(['scene']*4,i) for i in range(4)]==[None]*4
    assert router.images==2

def test_review_error_is_not_an_unchecked_pass(monkeypatch):
    monkeypatch.setattr('comic_images.has_lettering',lambda data:False)
    class Router(FakeSceneRouter):
        def _cloudflare_image(self,*a,**kw):return board()
        def _cloudflare_review_scene(self,*a,**kw):raise ProviderError('fixed review error')
    with pytest.raises(ProviderError,match='review error'):ComicImages(Router()).panel(['scene']*4,0)

def test_retry_feedback_uses_only_fixed_criteria():
    assert 'PRIVATE' not in retry_hint(['PRIVATE','action'])
