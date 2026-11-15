import test from 'node:test';
import assert from 'node:assert/strict';
import {IllustratedDiary,isImageDataURL,comicDialogue,comicArtworkHTML} from '../devtools/voice/illustration.mjs';

const image='data:image/png;base64,iVBORw0KGgo=';
const plan={diary_text:'공놀이를 했다. 즐거웠다.',diary_hash:'a'.repeat(64),storybook:{notices:[],scenes:[
  {scene_id:'storybook-1',order:1,caption:'공놀이를 했다.',source_ids:[0]},
  {scene_id:'storybook-2',order:2,caption:'즐거웠다.',source_ids:[1]}]}};
function result(ids,status='generated'){
  return {diary_hash:plan.diary_hash,source_ids:ids,caption:plan.storybook.scenes[ids[0]].caption,
    status,imageUrl:status==='generated'?image:null,error:null};
}

test('sequential images preserve approved captions and use current hash',async()=>{
  let inFlight=0,maxInFlight=0;const calls=[];
  const diary=new IllustratedDiary(async(path,body)=>{
    calls.push([path,body]);
    if(path==='/api/visual-story')return structuredClone(plan);
    inFlight++;maxInFlight=Math.max(maxInFlight,inFlight);await Promise.resolve();inFlight--;
    assert.equal(body.diary_hash,plan.diary_hash);assert.equal(body.confirmed,true);
    return result(body.source_ids);
  });
  await diary.build(plan.diary_text,2);
  assert.equal(maxInFlight,1);assert.equal(calls.length,3);
  assert.deepEqual(diary.state.scenes.map(s=>s.caption),plan.storybook.scenes.map(s=>s.caption));
  assert.ok(diary.state.scenes.every(s=>s.status==='generated'));
});

test('partial failure keeps successful image and retries only failed scene',async()=>{
  const ids=[];let failed=true;
  const diary=new IllustratedDiary(async(path,body)=>{
    if(path==='/api/visual-story')return structuredClone(plan);
    ids.push(body.source_ids[0]);
    if(body.source_ids[0]===0&&failed){failed=false;throw new Error('Groq 한도');}
    return result(body.source_ids);
  });
  await diary.build(plan.diary_text);assert.equal(diary.state.scenes[0].status,'failed');
  assert.equal(diary.state.scenes[1].imageUrl,image);
  await diary.retry(0);await diary.retry(1);
  assert.deepEqual(ids,[0,1,0]);assert.ok(diary.state.scenes.every(s=>s.status==='generated'));
});

test('rejected or mismatched image never appears',async()=>{
  const diary=new IllustratedDiary(async(path,body)=>{
    if(path==='/api/visual-story')return structuredClone(plan);
    return body.source_ids[0]===0?result([0],'rejected'):{...result([1]),diary_hash:'b'.repeat(64)};
  });
  await diary.build(plan.diary_text);
  assert.deepEqual(diary.state.scenes.map(s=>s.imageUrl),[null,null]);
  assert.deepEqual(diary.state.scenes.map(s=>s.status),['rejected','failed']);
});

test('cancelled late image is discarded and remaining pages are not called',async()=>{
  let finish,calls=0;const diary=new IllustratedDiary(async(path)=>{
    if(path==='/api/visual-story')return structuredClone(plan);
    calls++;return new Promise(resolve=>finish=resolve);
  });
  const pending=diary.build(plan.diary_text);await new Promise(resolve=>setImmediate(resolve));
  diary.cancel();finish(result([0]));await pending;
  assert.equal(calls,1);assert.equal(diary.busy,false);
  assert.ok(diary.state.scenes.every(s=>s.status==='cancelled'&&s.imageUrl===null));
});

test('invalid source lengths fail before network and blank diary is refused',async()=>{
  const diary=new IllustratedDiary(()=>{throw new Error('network must not run');});
  await assert.rejects(diary.build('  '),/일기/);
  await assert.rejects(diary.build('가'.repeat(6001)),/일기/);
  await assert.rejects(diary.build('test',0),/그림 수/);
});

test('standalone download embeds images, escapes text, and excludes scripts',()=>{
  const diary=new IllustratedDiary(()=>{});
  diary.state={diary_text:'<script>alert(1)</script>',created_at:'2026-11-06',scenes:[
    {caption:'<img src=x onerror="bad">',imageUrl:image,status:'generated'},
    {caption:'두 번째',imageUrl:'javascript:alert(1)',error:'<bad>'}]};
  const html=diary.html();
  assert.ok(html.includes(image));assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(!html.includes('<script>'));assert.ok(!html.includes('javascript:'));
  assert.ok(!isImageDataURL('data:image/svg+xml;base64,PHN2Zz4='));
  assert.ok(!isImageDataURL('https://example.com/image.png'));
});

test('four panel comic reuses identical short-story scenes without extra image calls',async()=>{
  let calls=0;const text='공놀이를 했다.';
  const scenes=Array.from({length:4},(_,i)=>({scene_id:`comic4-${i+1}`,caption:text,source_ids:[0],repeated:i>0,reuse_scene_id:i>0?'comic4-1':null}));
  const diary=new IllustratedDiary(async(path,body)=>{
    if(path==='/api/visual-story'){
      assert.equal(body.format,'comic4');return {diary_text:text,diary_hash:plan.diary_hash,comic4:{scenes,notices:['반복']}};
    }
    calls++;assert.equal(body.format,'comic4');return {...result([0]),caption:text};
  });
  await diary.build(text,4,'comic4');
  assert.equal(calls,1);assert.equal(diary.state.scenes.length,4);
  assert.ok(diary.state.scenes.every(s=>s.imageUrl===image));
});
test('retry of failed repeated comic panel regenerates only its original panel',async()=>{
  let calls=0;const text='공놀이를 했다.';
  const scenes=Array.from({length:4},(_,i)=>({scene_id:`comic4-${i+1}`,caption:text,source_ids:[0],repeated:i>0,reuse_scene_id:i>0?'comic4-1':null}));
  const diary=new IllustratedDiary(async(path)=>{
    if(path==='/api/visual-story')return {diary_text:text,diary_hash:plan.diary_hash,comic4:{scenes,notices:[]}};
    if(++calls===1)throw new Error('limit');return {...result([0]),caption:text};
  });
  await diary.build(text,4,'comic4');assert.ok(diary.state.scenes.every(s=>s.imageUrl===null));
  await diary.retry(3);assert.equal(calls,2);assert.ok(diary.state.scenes.every(s=>s.imageUrl===image));
});

test('comic dialogue preserves quoted source and never truncates or injects HTML',()=>{
  assert.equal(comicDialogue('탑을 완성하고 “우와, 완성했어!”라고 말했다.',['우와, 완성했어!']),'우와, 완성했어!');
  assert.equal(comicDialogue('블록을 쌓았다. 재미있었다.'),'');
  assert.equal(comicDialogue('가'.repeat(61)+'.'),'');
  const html=comicArtworkHTML({caption:'“<script>”라고 말했다.',imageUrl:image});
  assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<script>'));
  assert.ok(!comicArtworkHTML({caption:'실패',imageUrl:null}).includes('comic-dialogue'));
});


test('unknown image result keeps other images and prevents resubmitting the same draft',async()=>{
  let imageCalls=0;
  const diary=new IllustratedDiary(async(path,body)=>{
    if(path==='/api/visual-story')return structuredClone(plan);
    imageCalls++;
    if(body.source_ids[0]===0){
      throw Object.assign(new Error('이전 생성 결과를 확인해 주세요.'),{code:'IMAGE_RESULT_UNKNOWN'});
    }
    return result(body.source_ids);
  });
  await diary.build(plan.diary_text);
  assert.deepEqual(diary.state.scenes.map(scene=>scene.status),['unknown','generated']);
  assert.equal(diary.state.scenes[1].imageUrl,image);
  await diary.retry(0);
  await assert.rejects(diary.build(plan.diary_text),/이전 생성 결과/);
  assert.equal(imageCalls,2);
});
