// 실제 브라우저·API 없이 텍스트 대화·재시도·일기·만화와 음성 호출 차단을 검사합니다.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

test('text-only conversation, retry, diary, and comic without audio calls',async()=>{
  const nodes=new Map();
  const listeners={};
  const picture='data:image/png;base64,iVBORw0KGgo=';
  const ctx={fillRect(){},beginPath(){},arc(){},fill(){},moveTo(){},lineTo(){},stroke(){}};
  function element(){return {disabled:false,hidden:false,checked:true,value:'',textContent:'',children:[],width:960,height:600,
    setAttribute(){},getContext:()=>ctx,addEventListener:(name,fn)=>listeners[name]=fn,
    getBoundingClientRect:()=>({left:0,top:0,width:960,height:600}),setPointerCapture(){},toDataURL:()=>picture,
    append(...items){this.children.push(...items);},replaceChildren(){this.children=[];},click(){}};}
  const get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
  get('draft-panel').hidden=true;get('silence').value='3000';
  globalThis.document={getElementById:get,createElement:element,body:{dataset:{}},addEventListener(){}};
  globalThis.window=globalThis;globalThis.addEventListener=()=>{};
  const requests=[];
  const hash='a'.repeat(64);
  let imageAttempt=0,failChat=false;
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{
    async getUserMedia(){assert.fail('Text mode must not open the microphone');}}}});
  globalThis.MediaRecorder=class{constructor(){assert.fail('Text mode must not record');}};
  globalThis.speechSynthesis={cancel(){},speak(){assert.fail('Text mode must not speak');}};
  globalThis.fetch=async(path,options)=>{
    requests.push({path,body:options.body});let body;
    if(path==='/api/status')body={mode:'openai',configured:true};
    else if(path==='/api/chat'&&failChat){failChat=false;throw new Error('Synthetic network failure');}
    else if(path==='/api/chat')body={question:JSON.parse(options.body).messages.length?'기분이 어땠어?':'오늘은 무슨 일이 있었어?',finished:false};
    else if(path==='/api/diary')body={text:'친구와 공놀이를 했다.',fallback:false};
    else if(path==='/api/visual-story')body={diary_text:'친구와 공놀이를 했다.',diary_hash:hash,comic4:{notices:[],scenes:
      Array.from({length:4},(_,i)=>({scene_id:`comic4-${i+1}`,order:i+1,caption:'친구와 공놀이를 했다.',source_ids:[0],repeated:i>0,reuse_scene_id:i>0?'comic4-1':null}))}};
    else if(path==='/api/visual-story/image')body={diary_hash:hash,caption:'친구와 공놀이를 했다.',source_ids:[0],
      status:++imageAttempt===1?'failed':'generated',imageUrl:imageAttempt===1?null:picture,error:null};
    else throw new Error('Unexpected endpoint');
    return {ok:true,json:async()=>body};
  };
  const source=await readFile(new URL('../devtools/voice/app.js',import.meta.url),'utf8');
  const core=new URL('../devtools/voice/core.mjs',import.meta.url).href;
  const illustration=new URL('../devtools/voice/illustration.mjs',import.meta.url).href;
  const drawing=new URL('../devtools/voice/drawing.mjs',import.meta.url).href;
  await import('data:text/javascript;base64,'+Buffer.from(source.replace('/dev/voice/core.mjs',core).replace('/dev/voice/illustration.mjs',illustration).replace('/dev/voice/drawing.mjs',drawing)).toString('base64'));
  assert.equal(get('start').hidden,true);
  assert.equal(get('read-aloud').checked,false);
  await get('start').onclick(); // 숨겨진 이전 버튼을 직접 호출해도 음성을 시작하지 않습니다.
  assert.equal(requests.length,0);
  await get('text-start').onclick();
  assert.equal(requests.filter(r=>r.path==='/api/chat').length,1);
  get('text-input').value='친구와 공놀이를 했어. 즐거웠어.';
  // 한글 조합 중 Enter는 전송하지 않습니다.
  get('text-input').onkeydown({key:'Enter',isComposing:true,preventDefault(){assert.fail();}});
  assert.equal(requests.filter(r=>r.path==='/api/chat').length,1);
  failChat=true;
  await get('text-form').onsubmit({preventDefault(){}});
  assert.equal(get('text-input').value,'친구와 공놀이를 했어. 즐거웠어.');
  await get('text-form').onsubmit({preventDefault(){}});
  const submitted=JSON.parse(requests.filter(r=>r.path==='/api/chat').at(-1).body);
  assert.equal(submitted.messages.length,2); // 재시도에도 아이 발언은 한 번만 추가합니다.
  assert.equal(submitted.messages[1].text,'친구와 공놀이를 했어. 즐거웠어.');
  assert.equal(get('text-input').value,'');
  assert.ok(requests.every(r=>!['/api/transcribe','/api/speech','/api/voice-chat'].includes(r.path)));
  await get('diary').onclick();assert.equal(get('diary-text').textContent,'친구와 공놀이를 했다.');
  assert.equal(get('diary-panel').hidden,false);
  assert.equal(get('diary-edit').value,'친구와 공놀이를 했다.');
  assert.equal(get('diary-approved').checked,false);assert.equal(get('illustrate').disabled,true);
  await get('illustrate').onclick();assert.equal(imageAttempt,0); // 일기 확인 전에는 생성하지 않습니다.
  get('diary-approved').checked=true;get('diary-approved').onchange();
  await get('illustrate').onclick();assert.equal(imageAttempt,0); // 그림이 없으면 합치지 않습니다.
  const pointer={clientX:100,clientY:100,pointerId:1,button:0,preventDefault(){}};
  listeners.pointerdown(pointer);listeners.pointerup({...pointer,clientX:200});
  await get('illustrate').onclick();
  assert.equal(get('picture-panel').hidden,false);assert.equal(imageAttempt,0); // 원본 그림 합치기는 무료 로컬 처리입니다.
  assert.equal(get('drawing-preview').src,picture);assert.equal(get('diary-preview').textContent,'친구와 공놀이를 했다.');
  assert.equal(get('save-picture').disabled,false);
  await get('make-comic').onclick();assert.equal(imageAttempt,1);assert.equal(get('picture-cards').children.length,4);
  const retry=get('picture-cards').children[0].children.find(n=>n.textContent==='이 컷만 다시 만들기');
  assert.ok(retry);await retry.onclick();
  assert.equal(imageAttempt,2);assert.equal(get('save-picture').disabled,false);
  assert.equal(get('drawing-preview').src,picture); // 만화 재생성이 원본 그림을 바꾸지 않습니다.
  get('diary-edit').value='수정한 일기';get('diary-edit').oninput();
  assert.equal(get('picture-panel').hidden,true);assert.equal(get('diary-approved').checked,false);
});
