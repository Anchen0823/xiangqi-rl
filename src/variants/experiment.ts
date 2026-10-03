import type { Action, GameResult, Scenario, SearchResult, Seat } from './types';
import { other } from './types';
import { hash } from './random';
import { mirrorScenario, newGame, observe, play, rulesHash } from './rules';
import { search } from './search';
import type { Evaluator } from './features';

export interface ExperimentConfig {
  schemaVersion:1;
  id:string;
  pairs:number;
  nodes:number;
  rollout:number;
  seed:number;
  maxPlies:number;
  maxMillis?:number;
  purpose:'material'|'candidate';
  codeHash:string;
  modelHashes:[string|null,string|null];
  scenarioHash?:string;
}
export interface ExperimentRecord {
  schemaVersion:1;
  id:string;
  group:number;
  leg:number;
  configHash:string;
  rulesHash:string;
  scenario:Scenario;
  candidateSeat:Seat;
  candidateColor:string|null;
  result:GameResult;
  status:'complete'|'truncated'|'timeout'|'illegal'|'crash'|'error';
  error?:string;
  actions:Action[];
  searches:Omit<SearchResult,'policy'|'action'>[];
  searchSeeds:number[];
  finalKey:string;
}
export function schedule(base:Scenario,config:ExperimentConfig,group:number):{scenario:Scenario;seat:Seat;leg:number}[]{
  if(base.rules.mode==='banqi'){
    const flipped=structuredClone(base);flipped.pieces=flipped.pieces.map(p=>({...p,color:p.color==='red'?'black':'red'}));
    return [{scenario:base,seat:0,leg:0},{scenario:base,seat:1,leg:1},{scenario:flipped,seat:0,leg:2},{scenario:flipped,seat:1,leg:3}];
  }
  const seat:Seat=config.purpose==='material'&&base.focusColor?base.seats.indexOf(base.focusColor) as Seat:0;
  return [{scenario:base,seat,leg:0},{scenario:mirrorScenario(base),seat:other(seat),leg:1}];
}
export function validateExperiment(c:ExperimentConfig):void{
  if(c.schemaVersion!==1||!Number.isInteger(c.pairs)||c.pairs<1||!Number.isInteger(c.nodes)||c.nodes<1||!Number.isInteger(c.maxPlies)||c.maxPlies<1||!Number.isInteger(c.seed)||!Number.isInteger(c.rollout)||c.rollout<0)throw new Error('实验配置无效');
  if(c.purpose==='material'&&c.modelHashes[0]!==c.modelHashes[1])throw new Error('子力实验双方必须使用同一模型');
}
export async function playExperiment(scenario:Scenario,config:ExperimentConfig,group:number,leg:number,candidateSeat:Seat,evaluators:[Evaluator|undefined,Evaluator|undefined]=[undefined,undefined]):Promise<ExperimentRecord>{
  validateExperiment(config);let state=newGame(scenario);
  const record:ExperimentRecord={schemaVersion:1,id:`${config.id}-${group}-${leg}`,group,leg,configHash:hash(config),rulesHash:rulesHash(scenario.rules),scenario,candidateSeat,candidateColor:null,result:state.result,status:'truncated',actions:[],searches:[],searchSeeds:[],finalKey:state.keys.at(-1)!};
  try{
    while(state.result.kind==='ongoing'&&state.ply<config.maxPlies){
      const agent=state.turn===candidateSeat?0:1;
      const seed=(config.seed+group*100003+state.ply*997+agent*7919)>>>0;
      const response=await search(observe(state,state.turn),{nodes:config.nodes,rollout:config.rollout,seed,maxMillis:config.maxMillis},evaluators[agent]);
      const {action,policy:_,...metrics}=response;record.searches.push(metrics);record.searchSeeds.push(seed);
      if(response.status==='timeout'){record.status='timeout';break;}
      if(!action)throw new Error('AI 未返回动作');
      state=play(state,action);record.actions.push(action);
    }
    if(state.result.kind!=='ongoing')record.status='complete';
  }catch(e){record.error=e instanceof Error?e.message:String(e);record.status=record.error.includes('非法着法')?'illegal':'crash';}
  record.result=state.result;record.finalKey=state.keys.at(-1)!;record.candidateColor=state.seats[candidateSeat];return record;
}
const score=(r:ExperimentRecord)=>r.result.kind==='draw'?0.5:r.result.winner===r.candidateSeat?1:0;
const mean=(xs:number[])=>xs.length?xs.reduce((a,b)=>a+b,0)/xs.length:null;
export function interval(values:number[]):[number,number]|null{
  if(!values.length)return null;const m=mean(values)!;const radius=Math.sqrt(Math.log(40)/(2*values.length));return [Math.max(0,m-radius),Math.min(1,m+radius)];
}
export function summarize(records:ExperimentRecord[],config:ExperimentConfig,groupSize:number){
  const unique=new Map<string,ExperimentRecord>();
  for(const r of records){if(r.configHash!==hash(config)||r.group<0||r.group>=config.pairs||r.leg<0||r.leg>=groupSize||unique.has(`${r.group}:${r.leg}`))throw new Error('报告包含重复、越界或不兼容的对局');unique.set(`${r.group}:${r.leg}`,r);}
  const completed=records.filter(r=>r.status==='complete'&&r.result.kind!=='ongoing');
  const groups=Array.from({length:config.pairs},(_,g)=>completed.filter(r=>r.group===g)).filter(xs=>xs.length===groupSize);
  const scores=groups.map(xs=>mean(xs.map(score))!),wins=groups.map(xs=>mean(xs.map(r=>Number(r.result.kind==='win'&&r.result.winner===r.candidateSeat)))!);
  const total=config.pairs*groupSize,known=completed.reduce((sum,r)=>sum+score(r),0),unknown=total-completed.length;
  const breakdown=(subset:ExperimentRecord[])=>({games:subset.length,wins:subset.filter(r=>score(r)===1).length,draws:subset.filter(r=>score(r)===0.5).length,losses:subset.filter(r=>score(r)===0).length,scoreRate:mean(subset.map(score))});
  return {schemaVersion:1,config,scheduledGames:total,recordedGames:records.length,completeGroups:groups.length,...breakdown(completed),
    winRate:completed.length?completed.filter(r=>score(r)===1).length/completed.length:null,completionRate:completed.length/total,
    pairedScoreRate:mean(scores),score95:groups.length===config.pairs?interval(scores):null,win95:groups.length===config.pairs?interval(wins):null,
    completedGroupsScore95:interval(scores),intervalMethod:'Hoeffding on independent paired/group scores; per comparison, not simultaneous',
    allScheduledScoreBounds:[known/total,(known+unknown)/total],
    byFirst:{first:breakdown(completed.filter(r=>r.candidateSeat===r.scenario.turn)),second:breakdown(completed.filter(r=>r.candidateSeat!==r.scenario.turn))},
    byColor:{red:breakdown(completed.filter(r=>r.candidateColor==='red')),black:breakdown(completed.filter(r=>r.candidateColor==='black'))},
    failures:{truncated:records.filter(r=>r.status==='truncated').length,timeout:records.filter(r=>r.status==='timeout').length,illegal:records.filter(r=>r.status==='illegal').length,crash:records.filter(r=>r.status==='crash').length,error:records.filter(r=>r.status==='error').length,missing:total-records.length},
    warning:'弱引擎实验线索，仅适用于记录的规则、初始摆法、模型与预算。接近50%不能证明子力等价。未完成组不提供整体置信区间。'};
}
export function reportHtml(summary:ReturnType<typeof summarize>,records:ExperimentRecord[]):string{
  const escape=(x:unknown)=>String(x).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
  const pct=(n:number|null)=>n===null?'无有效样本':`${(n*100).toFixed(1)}%`;
  return `<!doctype html><meta charset="utf-8"><title>变体实验报告</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:20px;color:#21352f;background:#faf8f1}table{border-collapse:collapse;width:100%}td,th{padding:9px;border-bottom:1px solid #ccc;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}aside{padding:20px;background:#fff0cc}</style><h1>变体实验报告 · ${escape(summary.config.id)}</h1><aside>${escape(summary.warning)}</aside><p>完成 ${summary.games}/${summary.scheduledGames} 局，完整配对组 ${summary.completeGroups}/${summary.config.pairs}。</p><p>胜 / 和 / 负：${summary.wins} / ${summary.draws} / ${summary.losses}；纯胜率 ${pct(summary.winRate)}；得分率 ${pct(summary.scoreRate)}</p><p>95%得分区间：${summary.score95?summary.score95.map(pct).join(' — '):'未完成全部配对组，暂无整体区间'}；全部预定对局得分界限 ${summary.allScheduledScoreBounds.map(pct).join(' — ')}</p><table><tr><th>对局</th><th>状态</th><th>结果</th><th>步数</th><th>节点</th></tr>${records.map(r=>`<tr><td>${escape(r.id)}</td><td>${r.status}</td><td>${escape(r.result.reason||'尚未结束')}</td><td>${r.actions.length}</td><td>${r.searches.reduce((n,s)=>n+s.nodes,0)}</td></tr>`).join('')}</table><h2>配置、分项与不确定性</h2><pre>${escape(JSON.stringify(summary,null,2))}</pre>`;
}
