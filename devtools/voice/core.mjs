// 마이크·화면과 독립된 발화 종료 감지와 대화 이력 처리입니다.
export class TurnDetector {
  constructor({silenceMs=3000,threshold=0.018,maxMs=30000,start=0}={}) {
    Object.assign(this,{silenceMs,threshold,maxMs,start,last:start,lastVoice:start,voiceMs:0});
  }
  sample(rms,now) {
    const elapsed=Math.min(100,Math.max(0,now-this.last)); this.last=now;
    if(rms>=this.threshold){this.voiceMs+=elapsed;this.lastVoice=now;}
    if(now-this.start>=this.maxMs)return this.voiceMs>=250?'limit':'empty';
    if(this.voiceMs>=250&&now-this.lastVoice>=this.silenceMs)return 'end';
    return null;
  }
}

export class Conversation {
  constructor(request){this.request=request;this.messages=[];this.version=0;this.busy=false;}
  cancel(){this.version++;this.busy=false;}
  async ask(text=null){
    if(this.busy)throw new Error('이전 질문을 기다려 주세요.');
    const pending=this.messages.map(m=>({...m}));
    if(text!==null){
      text=text.trim();
      if(!text||text.length>2000)throw new Error('1~2,000자의 말을 입력해 주세요.');
      if(pending.length>58)throw new Error('이번 대화를 일기로 마무리해 주세요.');
      pending.push({role:'child',text});
    }
    this.busy=true;const version=this.version;
    try{
      const reply=await this.request('/api/chat',{messages:pending});
      if(version!==this.version)return null; // 중지/새 대화 이후 늦게 도착한 응답을 버립니다.
      if(typeof reply.question!=='string'||!reply.question.trim())throw new Error('질문 응답을 확인하지 못했습니다.');
      this.messages=[...pending,{role:'assistant',text:reply.question}];
      return reply;
    }finally{if(version===this.version)this.busy=false;}
  }
}
