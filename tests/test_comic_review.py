"""불일치·불완전 검사를 성공으로 처리하지 않는지 검사합니다. 외부 호출 없음."""
import pytest
from comic_review import parse_checks
from engine import ProviderError
from scene_prompting import SceneSpec


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

def test_complex_scene_objects_are_not_forced_to_count_one():
    item=scene();item.objects[0].name='family members'
    assert parse_checks(checks(object_counts=[3]),item)==[]
