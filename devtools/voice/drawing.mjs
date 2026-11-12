import {isImageDataURL,escapeHTML,comicArtworkHTML,COMIC_DIALOGUE_CSS} from './illustration.mjs';

// 원본 선을 보존하므로 되돌리기와 다시 그리기가 그림을 AI로 재생성하지 않습니다.
export class StrokeHistory {
  constructor(){this.strokes=[];this.past=[];this.future=[];this.current=null;}
  begin(point,{color='#28583e',width=6,tool='pen'}={}){
    if(this.strokes.length>=250)throw new Error('선이 많아요. 그림을 저장하거나 지우개로 정리해 주세요.');
    this.current={color:/^#[0-9a-f]{6}$/i.test(color)?color:'#28583e',width:Math.max(2,Math.min(30,Number(width)||6)),tool:tool==='eraser'?'eraser':'pen',points:[point]};
  }
  point(point){if(this.current&&this.current.points.length<4000)this.current.points.push(point);}
  commit(){if(!this.current)return;this.past.push(this.strokes);this.past=this.past.slice(-60);this.strokes=[...this.strokes,this.current];this.current=null;this.future=[];}
  clear(){if(!this.strokes.length)return;this.past.push(this.strokes);this.strokes=[];this.current=null;this.future=[];}
  undo(){if(!this.past.length)return;this.future.push(this.strokes);this.strokes=this.past.pop();this.current=null;}
  redo(){if(!this.future.length)return;this.past.push(this.strokes);this.strokes=this.future.pop();this.current=null;}
  get hasDrawing(){return this.strokes.some(stroke=>stroke.tool==='pen');}
}

export class DrawingPad {
  constructor(canvas,onChange=()=>{},onError=()=>{}){
    this.canvas=canvas;this.context=canvas.getContext('2d');this.history=new StrokeHistory();
    if(!this.context)throw new Error('이 브라우저에서 그림판을 사용할 수 없습니다.');
    this.onChange=onChange;this.onError=onError;this.disabled=false;this.pointer=null;
    this.options={color:'#28583e',width:6,tool:'pen'};
    canvas.addEventListener('pointerdown',event=>this.down(event));
    canvas.addEventListener('pointermove',event=>this.move(event));
    canvas.addEventListener('pointerup',event=>this.up(event));
    canvas.addEventListener('pointercancel',()=>{this.pointer=null;this.history.current=null;this.paint();});
    this.paint();
  }
  position(event){const r=this.canvas.getBoundingClientRect();return {
    x:Math.max(0,Math.min(1,(event.clientX-r.left)/r.width)),
    y:Math.max(0,Math.min(1,(event.clientY-r.top)/r.height))};}
  down(event){
    if(this.disabled||this.pointer!==null||(event.button!==undefined&&event.button!==0))return;
    event.preventDefault();
    try{this.history.begin(this.position(event),this.options);this.pointer=event.pointerId;this.canvas.setPointerCapture(event.pointerId);this.paint();}
    catch(error){this.onError(error);}
  }
  move(event){if(event.pointerId!==this.pointer||this.disabled)return;event.preventDefault();this.history.point(this.position(event));this.paint();}
  up(event){if(event.pointerId!==this.pointer)return;this.history.point(this.position(event));this.history.commit();this.pointer=null;this.paint();this.onChange();}
  setDisabled(value){this.disabled=value;this.canvas.setAttribute('aria-disabled',String(value));}
  undo(){if(this.disabled)return;this.history.undo();this.paint();this.onChange();}
  redo(){if(this.disabled)return;this.history.redo();this.paint();this.onChange();}
  clear(){if(this.disabled)return;this.history.clear();this.paint();this.onChange();}
  paint(){
    const ctx=this.context,{width,height}=this.canvas;
    ctx.fillStyle='#ffffff';ctx.fillRect(0,0,width,height);
    const strokes=[...this.history.strokes,...(this.history.current?[this.history.current]:[])];
    for(const stroke of strokes){
      ctx.lineCap='round';ctx.lineJoin='round';ctx.lineWidth=stroke.width;
      ctx.strokeStyle=ctx.fillStyle=stroke.tool==='eraser'?'#ffffff':stroke.color;
      const first=stroke.points[0];if(!first)continue;
      ctx.beginPath();ctx.arc(first.x*width,first.y*height,stroke.width/2,0,Math.PI*2);ctx.fill();
      ctx.beginPath();ctx.moveTo(first.x*width,first.y*height);
      for(const point of stroke.points.slice(1))ctx.lineTo(point.x*width,point.y*height);
      ctx.stroke();
    }
  }
  snapshot(){
    if(!this.history.hasDrawing)throw new Error('먼저 나만의 그림을 그려 주세요.');
    return this.canvas.toDataURL('image/png');
  }
}

export function drawingDiaryHTML({drawing,text,comic=null}){
  if(!isImageDataURL(drawing)||!text?.trim())throw new Error('그림과 확인한 일기를 먼저 합쳐 주세요.');
  const scenes=comic?.diary_text===text?comic.scenes:[];
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>내 그림일기와 4컷 만화</title>
<style>${COMIC_DIALOGUE_CSS}body{margin:0;background:#f5f5ef;color:#283b30;font:17px/1.8 -apple-system,BlinkMacSystemFont,sans-serif}main{max-width:1280px;padding:30px;margin:auto}.pair{display:grid;grid-template-columns:1fr 1fr;gap:24px;align-items:start}section{padding:22px;border:1px solid #d8e0d5;border-radius:14px;background:white}h1{font-size:25px}h2{font-size:19px}img{display:block;width:100%;height:auto}p{white-space:pre-wrap;overflow-wrap:anywhere}.comic{display:grid;grid-template-columns:1fr 1fr;gap:10px}.comic article{border:1px solid #d8e0d5;padding:10px;break-inside:avoid}.comic p{font-size:14px;margin:10px 0}.note{font-size:12px;color:#68776a}small{font-size:11px}@media(max-width:700px){.pair{grid-template-columns:1fr}main{padding:15px}}@media print{@page{size:A4 landscape;margin:10mm}body{background:white;font-size:12px}main{padding:0}.pair{grid-template-columns:1fr 1fr;gap:12px}section{padding:12px}h1{font-size:20px}.drawing{max-height:90mm;object-fit:contain}.comic img{max-height:55mm;object-fit:contain}.comic p{font-size:11px}}</style></head>
<body><main><h1>내 그림일기와 4컷 만화</h1><div class="pair"><section><h2>내가 그린 그림일기</h2><img class="drawing" src="${drawing}" alt="아이가 직접 그린 원본 그림"><p>${escapeHTML(text)}</p></section><section><h2>일기로 만든 AI 4컷 만화</h2>
${scenes.length?`<div class="comic">${scenes.map((scene,i)=>`<article><small>${i+1}컷${scene.repeated?' · 같은 장면':''}</small>${comicArtworkHTML(scene,comic.childSources)}<p>${escapeHTML(scene.caption)}</p></article>`).join('')}</div>`:'<p>4컷 만화를 아직 만들지 않았습니다.</p>'}
<p class="note">원문이 짧으면 같은 장면을 반복합니다. 새 사건이나 결말을 뜻하지 않습니다.</p></section></div><p class="note">왼쪽은 직접 그린 원본 그림입니다. 오른쪽은 확인한 일기에서 생성한 AI 삽화입니다. 사건이나 감정이 달라지지 않았는지 확인해 주세요.</p></main></body></html>`;
}
