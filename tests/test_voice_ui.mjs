// 실제 마이크·브라우저·API를 사용하지 않고 녹음/확인/응답/중지 연결을 검사합니다.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

test('microphone turn, transcript confirmation, next question, diary, and cleanup',async()=>{
  const nodes=new Map();
  function element(){return {disabled:false,hidden:false,checked:true,value:'',textContent:'',children:[],
    append(...items){this.children.push(...items);},replaceChildren(){this.children=[];},click(){}};}
  const get=id=>{if(!nodes.has(id))nodes.set(id,element());return nodes.get(id);};
  get('draft-panel').hidden=true;get('silence').value='3000';
  globalThis.document={getElementById:get,createElement:element,body:{dataset:{}},addEventListener(){}};
  globalThis.window=globalThis;globalThis.addEventListener=()=>{};
  let stopped=0,latest,transcriptions=0;const spoken=[],requests=[];
  const hash='a'.repeat(64),picture='data:image/png;base64,iVBORw0KGgo=';
  let imageAttempt=0;
  const track={readyState:'live',enabled:false,stop(){stopped++;this.readyState='ended';}};
  Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{
    async getUserMedia(){return {getTracks:()=>[track],getAudioTracks:()=>[track]};}}}});
  globalThis.AudioContext=class{
    state='running';resume(){return Promise.resolve();}close(){return Promise.resolve();}
    createAnalyser(){return {fftSize:2048,getFloatTimeDomainData(a){a.fill(0);}};}
    createMediaStreamSource(){return {connect(){},disconnect(){}};}
  };
  globalThis.MediaRecorder=class{
    static isTypeSupported(t){return t.startsWith('audio/webm');}
    state='inactive';constructor(stream,options){this.mimeType=options.mimeType;latest=this;}
    start(){this.state='recording';}
    stop(){this.state='inactive';this.ondataavailable?.({data:new Blob(['fake-audio'])});this.onstop?.();}
  };
  globalThis.SpeechSynthesisUtterance=class{constructor(text){this.text=text;}};
  globalThis.speechSynthesis={getVoices:()=>[{lang:'ko-KR',localService:true}],cancel(){},
    speak(u){spoken.push(u.text);setImmediate(()=>u.onend());}};
  globalThis.fetch=async(path,options)=>{
    requests.push({path,body:options.body});let body;
    if(path==='/api/status')body={mode:'openai',configured:true};
    else if(path==='/api/transcribe'){transcriptions++;body={text:'친구와 공놀이를 했어.',requires_confirmation:true};}
    else if(path==='/api/chat')body={question:JSON.parse(options.body).messages.length?'기분이 어땠어?':'오늘은 무슨 일이 있었어?',finished:false};
    else if(path==='/api/diary')body={text:'친구와 공놀이를 했다.',fallback:false};
    else if(path==='/api/visual-story')body={diary_text:'친구와 공놀이를 했다.',diary_hash:hash,storybook:{notices:[],scenes:[
      {scene_id:'storybook-1',order:1,caption:'친구와 공놀이를 했다.',source_ids:[0]}]}};
    else if(path==='/api/visual-story/image')body={diary_hash:hash,caption:'친구와 공놀이를 했다.',source_ids:[0],
      status:++imageAttempt===1?'failed':'generated',imageUrl:imageAttempt===1?null:picture,error:null};
    else throw new Error('Unexpected endpoint');
    return {ok:true,json:async()=>body};
  };
  const source=await readFile(new URL('../devtools/voice/app.js',import.meta.url),'utf8');
  const core=new URL('../devtools/voice/core.mjs',import.meta.url).href;
  const illustration=new URL('../devtools/voice/illustration.mjs',import.meta.url).href;
  await import('data:text/javascript;base64,'+Buffer.from(source.replace('/dev/voice/core.mjs',core).replace('/dev/voice/illustration.mjs',illustration)).toString('base64'));
  await get('start').onclick();
  assert.equal(latest.state,'recording');assert.equal(track.enabled,true);
  assert.deepEqual(spoken,['오늘은 무슨 일이 있었어?']);
  get('send-audio').onclick();
  for(let i=0;i<5;i++)await new Promise(resolve=>setImmediate(resolve));
  assert.equal(transcriptions,1);assert.equal(track.enabled,false);
  assert.equal(get('draft-panel').hidden,false);assert.equal(get('draft').value,'친구와 공놀이를 했어.');
  assert.equal(requests.filter(r=>r.path==='/api/chat').length,1); // 확인 전에는 질문을 만들지 않습니다.
  get('draft').value='친구와 공놀이를 했어. 즐거웠어.';
  await get('confirm').onclick();
  assert.equal(latest.state,'recording');assert.equal(get('draft-panel').hidden,true);
  const submitted=JSON.parse(requests.filter(r=>r.path==='/api/chat').at(-1).body);
  assert.equal(submitted.messages[1].text,'친구와 공놀이를 했어. 즐거웠어.');
  get('stop').onclick();assert.equal(track.readyState,'ended');assert.ok(stopped>=1);
  await get('diary').onclick();assert.equal(get('diary-text').textContent,'친구와 공놀이를 했다.');
  assert.equal(get('diary-panel').hidden,false);
  assert.equal(get('diary-edit').value,'친구와 공놀이를 했다.');
  assert.equal(get('diary-approved').checked,false);assert.equal(get('illustrate').disabled,true);
  await get('illustrate').onclick();assert.equal(imageAttempt,0); // 일기 확인 전에는 생성하지 않습니다.
  get('diary-approved').checked=true;get('diary-approved').onchange();get('picture-count').value='2';
  await get('illustrate').onclick();
  assert.equal(get('picture-panel').hidden,false);assert.equal(imageAttempt,1);
  assert.equal(get('save-picture').disabled,true);
  const retry=get('picture-cards').children[0].children.find(n=>n.textContent==='이 장면만 다시 만들기');
  assert.ok(retry);await retry.onclick();
  assert.equal(imageAttempt,2);assert.equal(get('save-picture').disabled,false);
  get('diary-edit').value='수정한 일기';get('diary-edit').oninput();
  assert.equal(get('picture-panel').hidden,true);assert.equal(get('diary-approved').checked,false);
});
