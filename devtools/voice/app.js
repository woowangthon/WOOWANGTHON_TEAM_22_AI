import {Conversation,TurnDetector} from '/dev/voice/core.mjs';
import {IllustratedDiary,isImageDataURL,comicBubble} from '/dev/voice/illustration.mjs';
import {DrawingPad,drawingDiaryHTML} from '/dev/voice/drawing.mjs';

const $=id=>document.getElementById(id);
// 현재 개발 화면은 텍스트 전용입니다. URL 옵션으로 음성을 켜지 않습니다.
const textOnly=true;
const pending=new Set();
let active=false,phase='idle',revision=0,stream=null,context=null,analyser=null,source=null;
let recorder=null,monitor=null,finishRecording=null,utterance=null,speechTimer=null,finishSpeech=null;
const MAX_BYTES=8*1024*1024;
let diaryMessageCount=null;
let composed=null; // 직접 그린 PNG와 사용자가 확인한 일기. 만화 생성과 별도로 보존합니다.

async function request(path,body){
  if(textOnly&&['/api/transcribe','/api/speech','/api/voice-chat'].includes(path)){
    throw new Error('현재는 텍스트 입력만 사용할 수 있어요.');
  }
  const controller=new AbortController();pending.add(controller);
  const timer=setTimeout(()=>controller.abort(),path==='/api/visual-story/image'?360000:120000);
  try{
    const options={method:body===undefined?'GET':'POST',signal:controller.signal,cache:'no-store'};
    if(body instanceof FormData)options.body=body;
    else if(body!==undefined){options.body=JSON.stringify(body);options.headers={'Content-Type':'application/json'};}
    const response=await fetch(path,options);
    let data;try{data=await response.json();}catch{throw new Error('서버 응답을 읽지 못했습니다. 서버 실행 상태를 확인해 주세요.');}
    if(!response.ok)throw new Error(typeof data.error==='string'?data.error:
      typeof data.detail==='string'?data.detail:`요청에 실패했습니다 (${response.status}).`);
    return data;
  }catch(error){
    if(error.name==='AbortError')throw new Error('요청이 중지되었거나 시간이 초과되었습니다.');
    throw error;
  }finally{clearTimeout(timer);pending.delete(controller);}
}
const conversation=new Conversation(request);
const illustrator=new IllustratedDiary(request,renderPictures);
const drawingPad=new DrawingPad($('drawing-canvas'),drawingChanged,showError);

function setPhase(next,message){
  phase=next;document.body.dataset.phase=next;$('status').textContent=message;
  const busy=['thinking','transcribing','speaking','diary','illustrating'].includes(next);
  $('text-start').disabled=busy||active;
  $('text-input').disabled=busy||active||!conversation.messages.length||next==='done';
  $('text-send').disabled=$('text-input').disabled;
  $('start').disabled=active||busy;
  $('stop').disabled=!active&&!busy;
  $('send-audio').disabled=next!=='listening';
  $('resume').disabled=!active||!['paused','ready'].includes(next)||!$('draft-panel').hidden;
  $('confirm').disabled=next!=='confirm';$('discard').disabled=next!=='confirm';
  $('diary').disabled=!conversation.messages.some(m=>m.role==='child')||busy||next==='listening'||!$('draft-panel').hidden;
  $('download').disabled=!conversation.messages.length;
  $('replay').disabled=busy||next==='listening'||!conversation.messages.some(m=>m.role==='assistant');
  syncPictureControls();
}
function syncPictureControls(){
  const busy=['thinking','transcribing','speaking','diary','illustrating','listening'].includes(phase);
  $('illustrate').disabled=busy||!$('diary-approved').checked||!$('diary-edit').value.trim()||!drawingPad.history.hasDrawing;
  $('diary-edit').disabled=busy;$('diary-approved').disabled=busy;drawingPad.setDisabled(busy);
  for(const id of ['draw-color','draw-width','draw-pen','draw-eraser'])$(id).disabled=busy;
  $('draw-undo').disabled=busy||!drawingPad.history.past.length;
  $('draw-redo').disabled=busy||!drawingPad.history.future.length;
  $('draw-clear').disabled=busy||!drawingPad.history.strokes.length;
  $('make-comic').disabled=busy||!composed;
  const ready=Boolean(composed)&&!illustrator.busy;
  $('save-picture').disabled=!ready;$('print-picture').disabled=!ready;
}
function showError(error){$('error').hidden=false;$('error').textContent=error.message||String(error);}
function clearError(){$('error').hidden=true;$('error').textContent='';}
function render(){
  const list=$('messages');list.replaceChildren();
  for(const message of conversation.messages){
    const item=document.createElement('li');item.className=message.role;
    const label=document.createElement('small');label.textContent=message.role==='assistant'?'AI 질문':'확인한 말';
    const content=document.createElement('span');content.textContent=message.text;
    item.append(label,content);list.append(item);
  }
  if(diaryMessageCount!==null&&diaryMessageCount!==conversation.messages.length){
    diaryMessageCount=null;composed=null;illustrator.clear();$('diary-panel').hidden=true;$('diary-approved').checked=false;
  }
}
function disableTracks(){if(stream)for(const track of stream.getTracks())track.enabled=false;}
function cancelSpeech(){
  const complete=finishSpeech;finishSpeech=null;clearTimeout(speechTimer);
  if('speechSynthesis' in window)window.speechSynthesis.cancel();
  utterance=null;if(complete)complete(false);
}
function releaseMic(){
  clearInterval(monitor);monitor=null;finishRecording=null;
  if(recorder?.state==='recording')recorder.stop();recorder=null;
  if(stream)stream.getTracks().forEach(track=>track.stop());stream=null;
  if(source)source.disconnect();source=null;
  if(context)context.close().catch(()=>{});context=null;analyser=null;$('level').value=0;
}
function stop(message='잠시 멈췄어요. 시작 버튼으로 이어갈 수 있어요.'){
  revision++;active=false;conversation.cancel();
  illustrator.cancel();
  for(const controller of pending)controller.abort();pending.clear();
  cancelSpeech();releaseMic();
  // 중지해도 인식한 초안은 남겨 두고 재개 후 확인하게 합니다.
  setPhase($('draft-panel').hidden?'idle':'confirm',message);
}
function fail(error,version){
  if(version!==revision)return;
  stop('연결을 확인한 뒤 다시 시작해 주세요.');showError(error);
}
async function ensureMic(){
  if(textOnly)throw new Error('현재는 텍스트 입력만 사용할 수 있어요.');
  if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder)throw new Error('이 브라우저에서 녹음을 지원하지 않습니다. 최신 Chrome에서 localhost 주소로 열어 주세요.');
  if(stream&&stream.getAudioTracks().some(track=>track.readyState==='live'))return;
  const version=revision;
  const AudioContext=window.AudioContext||window.webkitAudioContext;
  if(!AudioContext)throw new Error('이 브라우저는 마이크 음량 감지를 지원하지 않습니다.');
  const newContext=new AudioContext();
  try{
    await newContext.resume();
    const newStream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
    if(version!==revision){newStream.getTracks().forEach(t=>t.stop());await newContext.close();return;}
    context=newContext;stream=newStream;
    analyser=context.createAnalyser();analyser.fftSize=2048;
    source=context.createMediaStreamSource(stream);source.connect(analyser);disableTracks();
  }catch(error){await newContext.close().catch(()=>{});throw error;}
}
function say(text){
  if(textOnly)return Promise.resolve(false);
  cancelSpeech();disableTracks();
  if(!$('read-aloud').checked)return Promise.resolve(true);
  if(!('speechSynthesis' in window)){showError(new Error('기기 음성 출력을 지원하지 않습니다. 질문을 읽고 다시 말하기를 누르세요.'));return Promise.resolve(false);}
  const synth=window.speechSynthesis;
  const voices=synth.getVoices();
  // 설치된 한국어 음성을 우선합니다. 없는 경우 OS의 ko-KR 기본 음성을 요청합니다.
  const korean=voices.filter(v=>v.lang.toLowerCase().startsWith('ko'));
  const voice=korean.find(v=>v.localService)||korean[0];
  return new Promise(resolve=>{
    let done=false;
    const complete=ok=>{if(done)return;done=true;clearTimeout(speechTimer);finishSpeech=null;utterance=null;resolve(ok);};
    finishSpeech=complete;utterance=new SpeechSynthesisUtterance(text);utterance.lang='ko-KR';utterance.rate=0.93;
    if(voice)utterance.voice=voice;
    utterance.onend=()=>complete(true);
    utterance.onerror=()=>{showError(new Error('질문 음성이 재생되지 않았어요. 다시 듣거나 질문을 읽고 다시 말하기를 누르세요.'));complete(false);};
    speechTimer=setTimeout(()=>{synth.cancel();complete(false);},45000);
    synth.speak(utterance);
  });
}
async function handleReply(reply,version){
  if(!reply||version!==revision)return;
  render();$('draft-panel').hidden=true;$('draft').value='';
  setPhase('speaking','질문을 듣고 있어요.');
  const played=await say(reply.question);
  if(version!==revision)return;
  if(reply.finished){stop('대화를 마쳤어요. 일기 보기로 내용을 확인해 주세요.');return;}
  if(played&&active)await listen();
  else setPhase('paused','질문을 읽고 다시 말하기를 눌러 주세요.');
}
async function begin(){
  if(textOnly)return;
  if(active)return;clearError();active=true;const version=++revision;
  setPhase('thinking','마이크와 AI 연결을 준비하고 있어요.');
  try{
    const status=await request('/api/status');
    if(status.mode==='mock')throw new Error('실제 음성 인식에는 실제 AI 모드가 필요합니다. F5에서 실제 AI 설정을 선택해 주세요.');
    if(!status.configured)throw new Error('텍스트 공급자의 API 키를 설정하고 서버를 재시작해 주세요.');
    await ensureMic();if(version!==revision)return;
    if(!$('draft-panel').hidden){setPhase('confirm','인식한 내용을 확인하고 보내 주세요.');return;}
    const last=conversation.messages.filter(m=>m.role==='assistant').at(-1);
    const reply=last?{question:last.text,finished:false}:await conversation.ask();
    await handleReply(reply,version);
  }catch(error){
    if(error.name==='NotAllowedError')error=new Error('마이크 사용을 허용해 주세요. 브라우저 주소창의 사이트 설정에서 변경할 수 있습니다.');
    if(error.name==='NotFoundError')error=new Error('사용할 수 있는 마이크가 없습니다. Mac 입력 장치를 확인해 주세요.');
    fail(error,version);
  }
}
async function listen(){
  if(textOnly)return;
  if(!active||recorder||conversation.busy)return;
  const version=revision;clearError();
  try{
    await ensureMic();if(version!==revision||!stream)return;
    if(context.state!=='running')await context.resume();
    if(version!==revision)return;
    const preferred=['audio/webm;codecs=opus','audio/mp4','audio/webm'];
    const type=preferred.find(t=>MediaRecorder.isTypeSupported(t));
    if(!type)throw new Error('서버와 호환되는 녹음 형식이 없습니다. 최신 Chrome에서 시험해 주세요.');
    stream.getTracks().forEach(track=>track.enabled=true);
    const current=new MediaRecorder(stream,{mimeType:type});recorder=current;
    const chunks=[];let bytes=0,reason='manual';
    const detector=new TurnDetector({silenceMs:Number($('silence').value),start:performance.now()});
    current.ondataavailable=event=>{if(event.data.size){chunks.push(event.data);bytes+=event.data.size;if(bytes>MAX_BYTES)finish('oversize');}};
    const finish=why=>{
      if(current.state!=='recording')return;
      reason=why;clearInterval(monitor);monitor=null;finishRecording=null;
      disableTracks();setPhase('transcribing','말을 글로 옮기고 있어요.');current.stop();
    };
    finishRecording=()=>finish('manual');
    current.onerror=()=>{if(version===revision)fail(new Error('녹음 중 오류가 발생했습니다. 다시 시작해 주세요.'),version);};
    current.onstop=async()=>{
      if(recorder===current)recorder=null;
      if(version!==revision||!active)return;
      if(reason==='empty'){setPhase('paused','말소리가 감지되지 않았어요. 다시 말하기를 누르세요.');return;}
      if(reason==='oversize'||bytes>MAX_BYTES){setPhase('paused','녹음이 너무 커요. 더 짧게 말해 주세요.');return;}
      try{
        const blob=new Blob(chunks,{type:current.mimeType});
        if(!blob.size)throw new Error('녹음이 비어 있어요. 다시 말해 주세요.');
        const form=new FormData();form.append('file',blob,current.mimeType.includes('mp4')?'recording.m4a':'recording.webm');
        const transcript=await request('/api/transcribe',form);
        if(version!==revision)return;
        if(typeof transcript.text!=='string'||!transcript.text.trim())throw new Error('인식한 문장이 없어요. 다시 말해 주세요.');
        $('draft').value=transcript.text;$('draft-panel').hidden=false;
        setPhase('confirm',reason==='limit'?'30초까지 인식했어요. 확인하고 다음 말을 이어 주세요.':'인식한 내용을 확인해 주세요.');
        if(!$('confirm-first').checked)await sendDraft();
      }catch(error){if(version===revision){showError(error);setPhase('paused','다시 말하기로 녹음을 재시도할 수 있어요.');}}
    };
    current.start(1000);setPhase('listening','듣고 있어요. 편하게 이야기해 주세요.');
    const samples=new Float32Array(analyser.fftSize);
    monitor=setInterval(()=>{
      if(current.state!=='recording')return;
      analyser.getFloatTimeDomainData(samples);
      const rms=Math.sqrt(samples.reduce((sum,n)=>sum+n*n,0)/samples.length);$('level').value=rms;
      const result=detector.sample(rms,performance.now());if(result)finish(result);
    },50);
  }catch(error){fail(error,version);}
}
async function sendDraft(){
  if(phase!=='confirm')return;
  clearError();const text=$('draft').value.trim();const version=revision;
  if(!text){showError(new Error('인식한 문장을 입력하거나 다시 녹음해 주세요.'));return;}
  if(!active){showError(new Error('마이크로 대화 시작을 눌러 재개한 뒤 보내 주세요.'));return;}
  setPhase('thinking','다음 질문을 생각하고 있어요.');
  try{
    const reply=await conversation.ask(text);
    await handleReply(reply,version);
  }catch(error){if(version===revision){showError(error);setPhase('confirm','내용은 남아 있어요. 잠시 후 다시 보내 주세요.');}}
}
async function makeDiary(){
  if(!$('draft-panel').hidden){showError(new Error('먼저 인식한 내용을 확인해 보내 주세요.'));return;}
  stop('대화를 정리하고 있어요.');const version=revision;clearError();setPhase('diary','확인한 말로 일기를 만들고 있어요.');
  try{
    const diary=await request('/api/diary',{messages:conversation.messages});if(version!==revision)return;
    $('diary-text').textContent=diary.text;$('diary-note').textContent=diary.fallback?'생성 검사를 통과하지 못해 원문을 유지했습니다.':'말하지 않은 사건이나 감정이 없는지 확인해 주세요.';
    composed=null;illustrator.clear();diaryMessageCount=conversation.messages.length;
    $('diary-edit').value=diary.text;$('diary-approved').checked=false;
    $('diary-panel').hidden=false;setPhase('done','일기를 확인하고 나만의 그림을 그려 주세요.');
    $('diary-panel').scrollIntoView?.({behavior:'smooth',block:'start'});
  }catch(error){fail(error,version);}
}
function renderPictures(state){
  const cards=$('picture-cards');cards.replaceChildren();$('picture-panel').hidden=!composed;
  if(composed){$('drawing-preview').src=composed.drawing;$('diary-preview').textContent=composed.text;}
  if(!state){
    $('picture-progress').textContent='오른쪽 버튼으로 4컷 만화를 만들 수 있어요.';$('picture-notices').textContent='';
    syncPictureControls();return;
  }
  const complete=state.scenes.filter(scene=>scene.status==='generated').length;
  $('picture-progress').textContent=`만화 ${complete} / 4컷 완료${illustrator.busy?' · 순서대로 만들고 있어요.':''}`;
  $('picture-notices').textContent=state.notices.join(' ');
  state.scenes.forEach((scene,index)=>{
    const card=document.createElement('article');card.className='picture-page';
    const title=document.createElement('h3');title.textContent=`${index+1}컷${scene.repeated?' · 같은 장면':''}`;card.append(title);
    if(scene.status==='generated'&&isImageDataURL(scene.imageUrl)){
      const line=comicBubble(scene.caption,state.childSources);
      if(line){const bubble=document.createElement('p');bubble.className='comic-dialogue comic-'+line.kind;bubble.setAttribute('aria-label',line.kind==='thought'?'아이의 생각':'아이가 한 말');bubble.textContent=line.text;card.append(bubble);}
      const image=document.createElement('img');image.src=scene.imageUrl;image.alt=scene.caption;image.loading='lazy';card.append(image);
    }else{
      const placeholder=document.createElement('div');placeholder.className='picture-placeholder';
      placeholder.textContent=scene.status==='generating'?'그림을 만들고 원문과 비교하고 있어요…':scene.status==='waiting'?'앞 장면이 끝나면 만들어요.':scene.error||'그림을 만들지 못했어요.';
      card.append(placeholder);
      if(!illustrator.busy){
        const retry=document.createElement('button');retry.textContent=scene.repeated?'원본 컷 다시 만들기':'이 컷만 다시 만들기';
        retry.onclick=()=>retryPicture(index);card.append(retry);
      }
    }
    const caption=document.createElement('p');caption.className='picture-caption';caption.textContent=scene.caption;card.append(caption);cards.append(card);
  });
  syncPictureControls();
}
async function createPictures(){
  if(!$('diary-approved').checked){showError(new Error('일기 내용을 먼저 확인해 주세요.'));return;}
  try{
    const text=$('diary-edit').value.trim();
    if(!text||text.length>6000)throw new Error('일기를 1~6,000자로 확인해 주세요.');
    const drawing=drawingPad.snapshot();stop('내 그림과 일기를 합치고 있어요.');clearError();
    composed={text,drawing};
    if(illustrator.state&&illustrator.state.diary_text!==text)illustrator.clear();
    renderPictures(illustrator.state);$('diary-panel').hidden=true;
    setPhase('done','왼쪽 그림일기가 완성됐어요. 오른쪽에서 4컷 만화를 만들 수 있어요.');
    $('picture-panel').scrollIntoView?.({behavior:'smooth',block:'start'});
  }catch(error){showError(error);}
}
async function makeComic(){
  if(!composed||illustrator.busy)return;
  stop('4컷 만화를 준비하고 있어요.');const version=revision;clearError();
  setPhase('illustrating','확인한 일기로 4컷 만화를 만들고 있어요.');
  try{
    const result=await illustrator.build(composed.text,4,'comic4',{childSources:conversation.messages.filter(message=>message.role==='child').map(message=>message.text)});
    if(version!==revision||!result)return;
    const generated=result.scenes.filter(scene=>scene.status==='generated').length;
    setPhase('done',generated===4?'4컷 만화가 준비됐어요. 그림일기와 함께 확인해 주세요.':'내 그림일기는 그대로 있어요. 실패한 만화 컷만 다시 만들 수 있어요.');
  }catch(error){if(version===revision){showError(error);setPhase('done','내 그림일기는 남아 있어요. 설정을 확인한 뒤 다시 시도해 주세요.');}}
}
function drawingChanged(){
  composed=null;renderPictures(illustrator.state);
  $('drawing-note').textContent=drawingPad.history.hasDrawing?'내 그림이 있어요. 일기와 합치거나 더 그릴 수 있어요.':'아직 그림이 없어요. 편하게 그려 보세요.';
  syncPictureControls();
}
async function retryPicture(index){
  if(illustrator.busy)return;const version=revision;clearError();
  setPhase('illustrating','선택한 장면을 다시 만들고 있어요.');
  try{await illustrator.retry(index);if(version===revision)setPhase('done','장면 결과를 확인해 주세요.');}
  catch(error){if(version===revision){showError(error);setPhase('done','장면을 다시 만들지 못했어요.');}}
}
async function beginText(){
  if(conversation.busy)return;
  stop('텍스트 대화를 준비하고 있어요.');clearError();
  const version=revision;setPhase('thinking','첫 질문을 준비하고 있어요.');
  try{
    const status=await request('/api/status');
    if(version!==revision)return;
    if(!status.configured)throw new Error('텍스트 공급자의 API 키를 설정하고 서버를 재시작해 주세요.');
    if(!conversation.messages.length)await conversation.ask();
    if(version!==revision)return;
    render();setPhase('paused','답변을 입력한 뒤 보내기를 눌러 주세요.');$('text-input').focus?.();
  }catch(error){fail(error,version);}
}
async function sendText(){
  if($('text-send').disabled||conversation.busy)return;
  const text=$('text-input').value.trim();
  if(!text){showError(new Error('답변을 입력해 주세요.'));return;}
  const version=revision;clearError();setPhase('thinking','답변을 읽고 있어요.');
  try{
    const reply=await conversation.ask(text);
    if(!reply||version!==revision)return;
    $('text-input').value='';render();
    setPhase(reply.finished?'done':'paused',reply.finished?'대화를 마쳤어요. 일기 쓰기 버튼을 눌러 주세요.':'답변을 입력한 뒤 보내기를 눌러 주세요.');
    if(!reply.finished)$('text-input').focus?.();
  }catch(error){
    if(version===revision){showError(error);setPhase('paused','입력한 내용은 남아 있어요. 다시 보낼 수 있어요.');}
  }
}
$('text-start').onclick=beginText;
$('text-form').onsubmit=event=>{event.preventDefault();return sendText();};
$('text-input').onkeydown=event=>{
  if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing&&event.keyCode!==229){event.preventDefault();sendText();}
};
$('start').onclick=begin;
$('stop').onclick=()=>stop();
$('send-audio').onclick=()=>finishRecording?.();
$('resume').onclick=listen;
$('confirm').onclick=sendDraft;
$('discard').onclick=async()=>{$('draft').value='';$('draft-panel').hidden=true;if(active)await listen();else setPhase('idle','시작 버튼을 눌러 다시 이야기해 주세요.');};
$('diary').onclick=makeDiary;
$('illustrate').onclick=createPictures;
$('make-comic').onclick=makeComic;
$('draw-color').oninput=()=>{drawingPad.options.color=$('draw-color').value;selectDrawingTool('pen');};
$('draw-width').onchange=()=>{drawingPad.options.width=Number($('draw-width').value);};
function selectDrawingTool(tool){
  drawingPad.options.tool=tool;
  $('draw-pen').setAttribute('aria-pressed',String(tool==='pen'));
  $('draw-eraser').setAttribute('aria-pressed',String(tool==='eraser'));
}
$('draw-pen').onclick=()=>selectDrawingTool('pen');$('draw-eraser').onclick=()=>selectDrawingTool('eraser');
$('draw-undo').onclick=()=>drawingPad.undo();$('draw-redo').onclick=()=>drawingPad.redo();$('draw-clear').onclick=()=>drawingPad.clear();
$('diary-approved').onchange=syncPictureControls;
$('diary-edit').oninput=()=>{
  composed=null;illustrator.clear();$('diary-approved').checked=false;
  $('diary-note').textContent='수정한 내용을 다시 확인하고 내 그림과 합쳐 주세요.';syncPictureControls();
};
$('show-diary').onclick=()=>{$('diary-panel').hidden=!$('diary-panel').hidden;};
$('save-picture').onclick=()=>{
  try{
    const html=drawingDiaryHTML({...composed,comic:illustrator.state});
    const url=URL.createObjectURL(new Blob([html],{type:'text/html;charset=utf-8'}));
    const link=document.createElement('a');link.href=url;link.download='my-diary-and-comic.html';link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }catch(error){showError(error);}
};
$('print-picture').onclick=()=>window.print();
$('replay').onclick=async()=>{
  const text=conversation.messages.filter(m=>m.role==='assistant').at(-1)?.text;if(!text)return;
  const version=revision;setPhase('speaking','마지막 질문을 다시 들려드려요.');await say(text);
  if(version===revision)setPhase(active?'paused':'idle','다시 말하기 또는 시작 버튼을 눌러 주세요.');
};
$('download').onclick=()=>{
  const url=URL.createObjectURL(new Blob([JSON.stringify({messages:conversation.messages},null,2)],{type:'application/json'}));
  const link=document.createElement('a');link.href=url;link.download='conversation.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
document.addEventListener('visibilitychange',()=>{if(document.hidden&&(active||conversation.busy))stop('화면을 벗어나 요청을 중지했어요. 텍스트 대화 시작으로 이어갈 수 있어요.');});
window.addEventListener('pagehide',()=>stop());
if(textOnly){
  document.title='텍스트 대화 테스트';
  $('page-title').textContent='글로 하루를 이야기해 보세요';
  $('page-intro').textContent='마이크 없이 입력한 내용으로 AI와 대화하고 일기와 4컷 만화를 확인할 수 있어요.';
  for(const id of ['start','send-audio','resume','voice-options','level','replay'])$(id).hidden=true;
  $('read-aloud').checked=false;
  $('stop').textContent='요청 중지';
  $('voice-note').textContent='텍스트 대화 시작을 누르면 첫 질문이 나옵니다.';
}
setPhase('idle','대화를 시작해 주세요');
