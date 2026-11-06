import test from 'node:test';
import assert from 'node:assert/strict';
import {TurnDetector,Conversation} from '../devtools/voice/core.mjs';

test('silence alone never sends audio',()=>{
  const vad=new TurnDetector({start:0});
  for(let t=50;t<30000;t+=50)assert.equal(vad.sample(0,t),null);
  assert.equal(vad.sample(0,30000),'empty');
});
test('brief background click is not a spoken turn',()=>{
  const vad=new TurnDetector({start:0,silenceMs:1000});
  vad.sample(.1,50);for(let t=100;t<=3000;t+=50)assert.equal(vad.sample(0,t),null);
});
test('waits for speech and configured silence',()=>{
  const vad=new TurnDetector({start:0,silenceMs:1800});
  for(let t=50;t<=500;t+=50)assert.equal(vad.sample(.05,t),null);
  assert.equal(vad.sample(0,2200),null);
  assert.equal(vad.sample(0,2300),'end');
});
test('long turn stops at the duration limit',()=>{
  const vad=new TurnDetector({start:0});
  for(let t=50;t<30000;t+=50)vad.sample(.05,t);
  assert.equal(vad.sample(.05,30000),'limit');
});
test('failed question can be retried without duplicate child messages',async()=>{
  let calls=0;
  const convo=new Conversation(async()=>{if(calls++===0)throw new Error('limit');return {question:'어떤 놀이였어?'};});
  await assert.rejects(convo.ask('놀았어.'));
  assert.deepEqual(convo.messages,[]);
  await convo.ask('놀았어.');
  assert.deepEqual(convo.messages.map(m=>m.role),['child','assistant']);
});
test('cancelled late response is ignored',async()=>{
  let finish;const convo=new Conversation(()=>new Promise(resolve=>finish=resolve));
  const call=convo.ask('놀았어.');convo.cancel();finish({question:'어떤 놀이?'});
  assert.equal(await call,null);assert.deepEqual(convo.messages,[]);assert.equal(convo.busy,false);
});
test('concurrent requests are blocked',async()=>{
  let finish;const convo=new Conversation(()=>new Promise(resolve=>finish=resolve));
  const call=convo.ask('놀았어.');await assert.rejects(convo.ask('또 말했어.'),/기다려/);
  finish({question:'어떤 놀이?'});await call;
});
test('sends full history and preserves confirmed text',async()=>{
  const payloads=[];const convo=new Conversation(async(path,body)=>{payloads.push(body);return {question:'더 들려줄래?'};});
  await convo.ask();await convo.ask('친구랑 공놀이를 했어.');
  assert.equal(payloads[1].messages[0].role,'assistant');
  assert.equal(payloads[1].messages[1].text,'친구랑 공놀이를 했어.');
  assert.equal(convo.messages.length,3);
});
