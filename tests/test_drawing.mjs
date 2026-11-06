import test from 'node:test';
import assert from 'node:assert/strict';
import {StrokeHistory,DrawingPad,drawingDiaryHTML} from '../devtools/voice/drawing.mjs';

const image='data:image/png;base64,iVBORw0KGgo=';
test('drawing preserves original strokes through undo, redo, and reversible clear',()=>{
  const history=new StrokeHistory();
  history.begin({x:.1,y:.2},{color:'#ff0000',width:6});history.point({x:.8,y:.9});history.commit();
  const original=structuredClone(history.strokes);
  history.begin({x:.4,y:.4},{tool:'eraser',width:20});history.commit();
  history.undo();assert.deepEqual(history.strokes,original);history.redo();assert.equal(history.strokes.length,2);
  history.clear();assert.equal(history.hasDrawing,false);history.undo();assert.equal(history.strokes.length,2);
  assert.deepEqual(history.strokes[0],original[0]);
});
test('pointer coordinates stay correct when canvas is displayed at half size',()=>{
  const handlers={};let changed=0;
  const ctx={fillRect(){},beginPath(){},arc(){},fill(){},moveTo(){},lineTo(){},stroke(){}};
  const canvas={width:960,height:600,getContext:()=>ctx,addEventListener:(name,fn)=>handlers[name]=fn,
    getBoundingClientRect:()=>({left:10,top:20,width:480,height:300}),setPointerCapture(){},setAttribute(){},toDataURL:()=>image};
  const pad=new DrawingPad(canvas,()=>changed++);
  assert.throws(()=>pad.snapshot(),/그림/);
  const event=(x,y)=>({clientX:x,clientY:y,pointerId:1,button:0,preventDefault(){}});
  handlers.pointerdown(event(250,170));handlers.pointermove(event(490,320));handlers.pointerup(event(490,320));
  assert.deepEqual(pad.history.strokes[0].points[0],{x:.5,y:.5});
  assert.equal(pad.snapshot(),image);assert.equal(changed,1);
  pad.setDisabled(true);handlers.pointerdown(event(100,100));assert.equal(pad.history.current,null);
});
test('export includes original drawing on left, four comic panels on right, and escaped diary',()=>{
  const text='<script>공놀이</script>';
  const comic={diary_text:text,scenes:Array.from({length:4},(_,i)=>({caption:`${i+1}컷`,imageUrl:image,repeated:i>0}))};
  const html=drawingDiaryHTML({drawing:image,text,comic});
  assert.ok(html.includes('내가 그린 그림일기'));assert.ok(html.includes('AI 4컷 만화'));
  assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<script>'));
  assert.equal((html.match(/<article>/g)||[]).length,4);
  assert.equal((html.match(/src="data:image/g)||[]).length,5);
  assert.throws(()=>drawingDiaryHTML({drawing:'javascript:bad',text}),/그림/);
});
test('export excludes comic from a different approved diary',()=>{
  const html=drawingDiaryHTML({drawing:image,text:'수정한 일기',comic:{diary_text:'이전 일기',scenes:[{caption:'STALE',imageUrl:image}]}});
  assert.ok(!html.includes('STALE'));assert.ok(html.includes('아직 만들지 않았습니다'));
});
