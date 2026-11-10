"""그림용 명세의 근거·순서·구체적 행동 검사. 외부 API 호출 없음."""
import json
import time
import pytest
from engine import ProviderError
from scene_prompting import validate_specs, board_prompt
from providers import ProviderRouter

CAPTIONS=['파란 종이를 접었다.','완성한 비행기를 날렸다.','비행기가 바닥에 내려앉았다.','비행기를 주워 들었다.']

def candidate():
    return {'scenes':[{'index':i,'source_quote':caption,
        'objects':[{'name':'blue paper airplane','source_quote':'파란 종이'}],
        'action':['The narrator folds blue paper into an airplane.',
                  'The narrator launches the paper airplane forward.',
                  'The paper airplane rests on the floor.',
                  'The narrator picks up the paper airplane.'][i],
        'action_quote':caption,'mode':'actual'} for i,caption in enumerate(CAPTIONS)]}

def test_objects_and_actions_precede_style_and_source_quotes_are_not_drawn():
    prompt=board_prompt(validate_specs(candidate(),CAPTIONS))
    assert prompt.index('folds blue paper')<prompt.index('Thick brown')
    assert 'The cream mascot folds' in prompt and 'rests on the floor' in prompt
    assert '파란 종이' not in prompt and len(prompt)<=2048

@pytest.mark.parametrize('mutation', ['new_object','wrong_action_quote','wrong_order','empty_quote','verb_only','non_english'])
def test_invalid_specs_fail_instead_of_drawing(mutation):
    value=candidate()
    if mutation=='new_object':value['scenes'][0]['objects'][0]['source_quote']='언급하지 않은 나무'
    elif mutation=='wrong_action_quote':value['scenes'][0]['action_quote']=CAPTIONS[2]
    elif mutation=='wrong_order':value['scenes'].reverse()
    elif mutation=='empty_quote':value['scenes'][0]['objects'][0]['source_quote']=' '
    elif mutation=='verb_only':value['scenes'][0]['action']='fold'
    else:value['scenes'][0]['action']='종이비행기를 접는다'
    with pytest.raises(ProviderError):validate_specs(value,CAPTIONS)

def test_cannot_use_later_scene_as_object_evidence():
    value=candidate();value['scenes'][0]['objects'][0]['source_quote']='바닥'
    with pytest.raises(ProviderError):validate_specs(value,CAPTIONS)

def test_neutral_scene_does_not_turn_wish_into_actual_action():
    value=candidate();value['scenes'][0]['mode']='neutral'
    prompt=board_prompt(validate_specs(value,CAPTIONS))
    assert 'Top left: neutral cream mascot, plain background.' in prompt
    assert 'folds blue paper' not in prompt

@pytest.mark.parametrize('finish,content',[('length',json.dumps(candidate())),('stop','not JSON'),('stop','{}')])
def test_incomplete_scene_provider_output_is_safe(monkeypatch,finish,content):
    router=ProviderRouter()
    monkeypatch.setattr(router,'_cloudflare_request',lambda *a,**kw:{'choices':[{
        'finish_reason':finish,'message':{'content':content}}]})
    with pytest.raises(ProviderError):router._cloudflare_scene_specs(CAPTIONS,deadline=time.monotonic()+10)


def test_provider_constrains_evidence_to_exact_original_captions(monkeypatch):
    router=ProviderRouter();calls=[]
    def request(model,payload,**kw):
        calls.append((model,payload))
        return {'response':candidate()}
    monkeypatch.setattr(router,'_cloudflare_request',request)
    router._cloudflare_scene_specs(CAPTIONS,deadline=time.monotonic()+10)
    model,payload=calls[0]
    assert model=='@cf/meta/llama-3.3-70b-instruct-fp8-fast'
    assert payload['response_format']['type']=='json_schema'
    schema=payload['response_format']['json_schema']
    assert schema['$defs']['SceneSpec']['properties']['action_quote']['enum']==CAPTIONS
