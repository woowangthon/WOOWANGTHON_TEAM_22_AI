from token_budget import compact_payload, completion_budget
from models import Review, QuestionCandidate, DiaryCandidate
from engine import DiaryEngine
from test_diary import FakeAdapter, conversation
import json


def test_lossless_compaction_preserves_source_positions_and_context():
    messages=[m.model_dump() for m in conversation()]
    sources=[{'id':i,'text':m['text']} for i,m in enumerate(messages) if m['role']=='child']
    original={'conversation':messages,'sources':sources,'candidate':{'sentences':[]}}
    instruction,data=compact_payload('rules',original)
    assert 'sources' not in data and 'sources' in original
    assert [{'role':row[1],'text':row[2]} for row in data['conversation']]==messages
    assert [{'id':r[0],'text':r[2]} for r in data['conversation'] if r[1]=='child']==sources
    assert len(json.dumps(data))<len(json.dumps(original))
    assert 'assistant' in instruction


def test_nonidentical_sources_are_never_dropped():
    _,data=compact_payload('rules',{'conversation':[{'role':'child','text':'원문'}], 'sources':[{'id':7,'text':'다른 원문'}]})
    assert data['sources']==[{'id':7,'text':'다른 원문'}]


def test_stage_specific_output_caps():
    assert completion_budget(Review)==512
    assert completion_budget(QuestionCandidate)==768
    assert completion_budget(DiaryCandidate)==2048
