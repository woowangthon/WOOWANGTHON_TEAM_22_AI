import test from 'node:test';
import assert from 'node:assert/strict';
import {comicBubble,comicArtworkHTML,IllustratedDiary} from '../devtools/voice/illustration.mjs';
const image='data:image/png;base64,iVBORw0KGgo=';

test('speech requires exact child source, without rewriting',()=>{
  const caption='나는 “다시 해 볼래!”라고 말했다.';
  assert.deepEqual(comicBubble(caption,['나는 “다시 해 볼래!”라고 말했어.']),{text:'다시 해 볼래!',kind:'speech'});
  assert.equal(comicBubble(caption,[]),null);
  assert.equal(comicBubble(caption,['나는 다시 하고 싶었어.']),null);
});
test('explicit thought keeps its wording and is distinguished from speech',()=>{
  const caption='나는 마음속으로 “내일 또 하고 싶어”라고 생각했다.';
  assert.deepEqual(comicBubble(caption,['나는 마음속으로 “내일 또 하고 싶어”라고 생각했어.']),{text:'내일 또 하고 싶어',kind:'thought'});
  const html=comicArtworkHTML({caption,imageUrl:image},['내일 또 하고 싶어']);
  assert.ok(html.includes('comic-thought')&&html.includes('아이의 생각'));
});
test('other speakers, assistant messages and negated speech are excluded',()=>{
  for(const caption of ['친구가 “잘했어!”라고 말했다.','민수가 “잘했어!”라고 말했다.','“잘했어!”라고 친구가 말했다.','나는 “잘했어!”라고 말하지 않았다.']){
    assert.equal(comicBubble(caption,[caption]),null);
  }
  assert.equal(comicBubble('나는 “잘했어!”라고 말했다.',[{role:'assistant',text:'잘했어!'}]),null);
});
test('latest explicit denial is not replaced by an old quote',()=>{
  const caption='나는 “다시 할래”라고 말했다.';
  assert.equal(comicBubble(caption,['나는 “다시 할래”라고 말했어.','나는 “다시 할래”라고 말하지 않았어.']),null);
});
test('long text is omitted rather than truncated, and markup is escaped',()=>{
  const long='안'.repeat(41);assert.equal(comicBubble(`나는 “${long}”라고 말했다.`,[long]),null);
  const html=comicArtworkHTML({caption:'나는 “<script>”라고 말했다.',imageUrl:image},['<script>']);
  assert.ok(html.includes('&lt;script&gt;')&&!html.includes('<script>'));
});
test('export retains verified bubbles only when source texts are present',()=>{
  const diary=new IllustratedDiary(()=>{});
  diary.state={format:'comic4',diary_text:'나는 “해냈어!”라고 말했다.',childSources:['해냈어!'],created_at:'example',scenes:[{caption:'나는 “해냈어!”라고 말했다.',imageUrl:image}]};
  assert.ok(diary.html().includes('comic-speech'));
  diary.state.childSources=[];assert.ok(!diary.html().includes('class="comic-dialogue comic-speech"'));
});
