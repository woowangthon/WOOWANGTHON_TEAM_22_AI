// 그림일기 구성·장면별 생성·실패 재시도·내려받기를 UI와 독립적으로 처리합니다.
export const isImageDataURL=value=>typeof value==='string'&&/^data:image\/(png|jpeg);base64,[A-Za-z0-9+/]+={0,2}$/.test(value);
export const escapeHTML=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

// 말풍선은 새로 생성하지 않고, 장면 글과 아이 원문에 함께 존재하는 짧은 문장만 선택합니다.
const MAX_BUBBLE=40;
const short=text=>Array.from(text).length<=MAX_BUBBLE;
const quotePattern=/“([^”\n]+)”|「([^」\n]+)」|"([^"\n]+)"|‘([^’\n]+)’/gu;
const childTexts=sources=>(Array.isArray(sources)?sources:[]).filter(s=>typeof s==='string'||(s&&(!s.role||s.role==='child'))).map(s=>typeof s==='string'?s:s.text).filter(s=>typeof s==='string');
function attribution(before,after){
  before=before.replace(/[“「"‘]$/u,'');after=after.replace(/^[”」"’]/u,'');
  const left=before.split(/[.!?。\n]/u).at(-1)||'';
  const subjects=[...left.matchAll(/(?:^|\s)([가-힣]{1,12})([이가은는])(?=\s|[“「"‘])/gu)];
  const last=subjects.at(-1)?.[1];
  if(last&&!['나','내','저'].includes(last))return 'other';
  if(/(?:친구|엄마|아빠|선생님|동생|언니|오빠|누나|할머니|할아버지)(?:가|는|이|은)?[^.!?。\n]{0,12}$/u.test(left)&&!/(?:나는|내가|난|나도)[^.!?。\n]{0,10}$/u.test(left))return 'other';
  if(/^(?:이?라고|라며|하며|하고)?\s*(?:(?:친구|엄마|아빠|선생님|동생|[가-힣]{1,8})(?:가|는|이|은))\s*(?:말|생각)/u.test(after))return 'other';
  if(/말하지\s*않|생각하지\s*않|안\s*말했|(?:말|생각)(?:한|했)[^.!?。\n]{0,12}아니|말한\s*적[^.!?。\n]{0,8}없|예를\s*들|가정/u.test(left+' '+after))return 'uncertain';
  return /마음속|속으로|생각했|생각했다|생각이\s*들/u.test(left+' '+after)?'thought':'speech';
}
function support(text,sources){
  for(const source of [...sources].reverse()){
    let index=source.indexOf(text);
    while(index>=0){
      const kind=attribution(source.slice(Math.max(0,index-70),index),source.slice(index+text.length,index+text.length+40));
      if(kind==='speech'||kind==='thought')return kind;
      index=source.indexOf(text,index+text.length);
    }
    if(source.includes(text))return null; // 최신 발언의 부정을 이전 인용으로 덮지 않습니다.
  }
  return null;
}
export function comicBubble(caption,childSources=[]){
  const text=String(caption||'').trim(),sources=childTexts(childSources);
  if(!text||!sources.length)return null;
  for(const match of text.matchAll(quotePattern)){
    const line=match[1]||match[2]||match[3]||match[4];
    if(!short(line)||!line.trim())continue;
    const kind=attribution(text.slice(Math.max(0,match.index-70),match.index),text.slice(match.index+match[0].length,match.index+match[0].length+40));
    const original=support(line,sources);
    if(original&&['speech','thought'].includes(kind))return {text:line,kind:kind==='thought'||original==='thought'?'thought':'speech'};
  }
  // 직접 인용이 없어도 아이가 실제 입력한 짧은 문장이 장면 글에 그대로 있으면 사용할 수 있습니다.
  for(const source of [...sources].reverse()){
    const sentences=source.match(/[^.!?。\n]+[.!?。]?/gu)||[];
    for(const sentence of sentences){
      const line=sentence.trim();
      if(!line||!short(line)||!text.includes(line)||/[“”「」"‘’]/u.test(line))continue;
      if(!/^(?:나는|내가|난|나도|내\s)|(?:기뻤|슬펐|속상했|재미있|좋았|싶어|싶었|궁금했)/u.test(line))continue;
      const kind=attribution(line,'');
      if(['speech','thought'].includes(kind))return {text:line,kind:/생각|마음|싶어|싶었|궁금/u.test(line)?'thought':kind};
    }
  }
  return null;
}

// 기존 JS 함수 호출부와의 호환용 래퍼입니다. 출처가 없으면 말풍선을 표시하지 않습니다.
export const comicDialogue=(caption,childSources=[])=>comicBubble(caption,childSources)?.text||'';
export function comicArtworkHTML(scene,childSources=[]){
  if(!isImageDataURL(scene.imageUrl))return `<p class="note">${escapeHTML(scene.error||'그림이 아직 생성되지 않았습니다.')}</p>`;
  const bubble=comicBubble(scene.caption,childSources);
  return `<div class="comic-art">${bubble?`<p class="comic-dialogue comic-${bubble.kind}" aria-label="${bubble.kind==='thought'?'아이의 생각':'아이가 한 말'}">${escapeHTML(bubble.text)}</p>`:''}<img src="${scene.imageUrl}" alt="${escapeHTML(scene.caption)}"></div>`;
}
export const COMIC_DIALOGUE_CSS='.comic-dialogue{position:relative;box-sizing:border-box;background:#fffef7;color:#493c32;border:2px solid #68513f;border-radius:18px;padding:10px 14px;margin:8px 8px 14px;font-size:15px;line-height:1.5;white-space:pre-wrap;overflow-wrap:anywhere}.comic-thought{border-style:dashed;border-radius:28px}.comic-dialogue:after{content:"";position:absolute;bottom:-8px;left:24px;width:12px;height:12px;background:#fffef7;border-right:2px solid #68513f;border-bottom:2px solid #68513f;transform:rotate(45deg)}'+'.comic-thought:after{border:2px dotted #68513f;border-radius:50%;width:10px;height:10px;transform:none;bottom:-10px;left:24px}.comic-thought:before{content:"";position:absolute;width:5px;height:5px;border:1px solid #68513f;border-radius:50%;background:#fffef7;bottom:-18px;left:18px}';

export class IllustratedDiary {
  constructor(request,onChange=()=>{}){this.request=request;this.onChange=onChange;this.state=null;this.busy=false;this.version=0;}
  cancel(){
    this.version++;this.busy=false;
    if(this.state){
      for(const scene of this.state.scenes)if(['waiting','generating'].includes(scene.status)){
        scene.status='cancelled';scene.error='생성을 중지했습니다. 이 장면만 다시 만들 수 있습니다.';
      }
      this.onChange(this.state);
    }
  }
  clear(){this.cancel();this.state=null;this.onChange(null);}
  async build(text,pages=2,format='storybook',options={}){
    if(this.busy)throw new Error('그림을 만들고 있어요. 잠시 기다려 주세요.');
    text=text.trim();
    if(!text||text.length>6000)throw new Error('확인한 일기를 1~6,000자로 입력해 주세요.');
    if(!Number.isInteger(pages)||pages<1||pages>6)throw new Error('그림 수를 1~6장으로 선택해 주세요.');
    if(!['storybook','comic4'].includes(format))throw new Error('지원하지 않는 그림 형식입니다.');
    const version=++this.version;this.busy=true;
    try{
      const plan=await this.request('/api/visual-story',{diary_text:text,confirmed:true,format,storybook_pages:pages});
      if(version!==this.version)return null;
      const document=plan[format];
      if(!document?.scenes?.length||!plan.diary_hash||(format==='comic4'&&document.scenes.length!==4))throw new Error('그림일기 장면 구성을 받지 못했습니다.');
      this.state={diary_text:plan.diary_text,diary_hash:plan.diary_hash,format,
        notices:document.notices||[],created_at:new Date().toISOString(),childSources:childTexts(options.childSources),
        scenes:document.scenes.map(scene=>({...scene,imageUrl:null,status:'waiting',error:null}))};
      this.onChange(this.state);
      // 무료 한도와 중복 과금을 줄이기 위해 각 장면은 순서대로 한 번만 요청합니다.
      for(let i=0;i<this.state.scenes.length;i++){
        if(version!==this.version)return null;
        await this.generate(i,version);
      }
      return version===this.version?this.state:null;
    }finally{if(version===this.version){this.busy=false;this.onChange(this.state);}}
  }
  async generate(index,version){
    const state=this.state,scene=state.scenes[index];
    if(scene.repeated&&scene.reuse_scene_id){
      this.reuseScene(scene);this.onChange(state);return;
    }
    scene.status='generating';scene.error=null;this.onChange(state);
    try{
      const result=await this.request('/api/visual-story/image',{
        diary_text:state.diary_text,diary_hash:state.diary_hash,
        source_ids:scene.source_ids,format:state.format||'storybook',confirmed:true});
      if(version!==this.version)return;
      if(result.diary_hash!==state.diary_hash||result.caption!==scene.caption||
          JSON.stringify(result.source_ids)!==JSON.stringify(scene.source_ids)){
        throw new Error('그림의 근거와 현재 일기가 일치하지 않습니다. 일기를 다시 확인해 주세요.');
      }
      if(result.status==='generated'&&isImageDataURL(result.imageUrl)){
        scene.imageUrl=result.imageUrl;scene.status='generated';
      }else{
        scene.status=result.status==='rejected'?'rejected':'failed';scene.imageUrl=null;
        scene.error=result.error||(result.status==='rejected'?'원문과 일치하는지 확인하지 못해 그림을 표시하지 않았어요.':
          result.status==='mock'?'체험 모드에서는 실제 그림을 만들지 않아요. 실제 AI 모드로 실행해 주세요.':'그림을 받지 못했어요. 키와 무료 한도를 확인해 주세요.');
      }
    }catch(error){if(version===this.version){scene.status='failed';scene.error=error.message;scene.imageUrl=null;}}
    if(version===this.version){
      for(const repeated of state.scenes)if(repeated.reuse_scene_id===scene.scene_id)this.reuseScene(repeated);
      this.onChange(state);
    }
  }
  reuseScene(scene){
    const original=this.state.scenes.find(s=>s.scene_id===scene.reuse_scene_id);
    if(!original||JSON.stringify(original.source_ids)!==JSON.stringify(scene.source_ids)){
      scene.status='failed';scene.imageUrl=null;scene.error='반복 컷의 근거가 일치하지 않습니다.';return;
    }
    scene.imageUrl=original.imageUrl;scene.status=original.status;
    scene.error=original.error?'원본 컷을 다시 만들면 이 반복 컷도 함께 갱신됩니다.':null;
  }
  async retry(index){
    if(this.busy)throw new Error('현재 그림 생성이 끝난 뒤 다시 시도해 주세요.');
    const scene=this.state?.scenes[index];if(!scene||scene.status==='generated')return;
    if(scene.repeated&&scene.reuse_scene_id){
      const original=this.state.scenes.findIndex(s=>s.scene_id===scene.reuse_scene_id);
      if(original<0)throw new Error('원본 컷을 찾지 못했습니다.');
      if(this.state.scenes[original].status==='generated'){this.reuseScene(scene);this.onChange(this.state);return;}
      index=original;
    }
    const version=++this.version;this.busy=true;
    try{await this.generate(index,version);}finally{if(version===this.version){this.busy=false;this.onChange(this.state);}}
  }
  html(){
    if(!this.state)throw new Error('먼저 그림일기를 만들어 주세요.');
    const {scenes,diary_text,created_at}=this.state;
    return `<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>그림일기</title>
<style>${COMIC_DIALOGUE_CSS}body{font:18px/1.8 -apple-system,BlinkMacSystemFont,sans-serif;color:#273b30;background:#f4f5ef;margin:0}main{max-width:760px;margin:auto;padding:32px 20px}article{background:white;padding:24px;border:1px solid #d9e0d5;border-radius:14px;margin:24px 0;break-inside:avoid}img{display:block;width:100%;height:auto;border-radius:8px}p{white-space:pre-wrap;overflow-wrap:anywhere}.note{font-size:13px;color:#657364}@media print{body{background:white}article{break-after:page;border:0}summary{display:none}details>p{display:block}}</style>
<main><h1>${this.state.format==='comic4'?'AI 4컷 만화':'그림일기'}</h1><p class="note">출력 생성 시각: ${escapeHTML(created_at)} · 기록한 사건의 날짜를 뜻하지 않습니다.</p>
<div style="${this.state.format==='comic4'?'display:grid;grid-template-columns:1fr 1fr;gap:16px':''}">${scenes.map((scene,i)=>`<article><h2>${i+1}번째 장면</h2>${this.state.format==='comic4'?comicArtworkHTML(scene,this.state.childSources):isImageDataURL(scene.imageUrl)?`<img src="${scene.imageUrl}" alt="${escapeHTML(scene.caption)}">`:`<p class="note">${escapeHTML(scene.error||'그림이 아직 생성되지 않았습니다.')}</p>`}<p>${escapeHTML(scene.caption)}</p></article>`).join('')}</div>
<details><summary>일기 글 보기</summary><p>${escapeHTML(diary_text)}</p></details><p class="note">확인한 일기를 바탕으로 만든 AI 삽화입니다. 원문과 다른 부분이 없는지 확인해 주세요.</p></main></html>`;
  }
}
