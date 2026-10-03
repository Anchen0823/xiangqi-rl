import type { Observation, ModelManifest } from './types';
import { actionIndex } from './types';

export const FEATURE_VERSION='lab-features-v1' as const;
export const ACTION_SIZE=8190;
// 32 type channels + 32 public-role channels + 3 ownership channels + hidden.
export const CELL_FEATURES=68;
export const INPUT_SIZE=90*CELL_FEATURES+128+16;
export function encode(o:Observation):Float32Array{
  const out=new Float32Array(INPUT_SIZE), kinds=o.rules.pieces.map(p=>p.id).sort(), own=o.seats[o.viewer];
  for(const p of o.pieces){const offset=p.square*CELL_FEATURES;
    if(p.kind!==null){const index=kinds.indexOf(p.kind);if(index>=0)out[offset+index]=1;}
    const role=kinds.indexOf(p.role);if(role>=0)out[offset+32+role]=1;
    out[offset+64+(p.color===null||own===null?2:p.color===own?0:1)]=1;
    out[offset+67]=Number(p.hidden);
  }
  let offset=90*CELL_FEATURES;
  for(const x of o.inventory){const index=kinds.indexOf(x.kind);if(index>=0)out[offset+(x.color==='red'?0:32)+index]=x.count/90;}
  offset+=64;
  for(const c of o.captures){const index=c.kind===null?-1:kinds.indexOf(c.kind);if(index>=0)out[offset+(c.color==='red'?0:32)+index]+=1/90;}
  offset+=64;
  out[offset]=o.turn===o.viewer?1:-1;out[offset+1]=own==='red'?1:own==='black'?-1:0;
  out[offset+2]=o.quiet/o.rules.quietLimit;out[offset+3]=Math.min(o.ply/1000,1);
  out[offset+4]=o.rules.mode==='custom'?1:0;out[offset+5]=o.rules.mode==='jieqi'?1:0;out[offset+6]=o.rules.mode==='banqi'?1:0;
  out[offset+7]=o.rules.width/9;out[offset+8]=o.rules.height/10;
  out[offset+9]=o.captures.filter(c=>c.kind===null).length/32;
  out[offset+10]=o.keys.filter(k=>k===o.keys.at(-1)).length/3;
  for(const [i,seat]of [o.viewer,(1-o.viewer)].entries()){const moves=o.history.slice(-16).filter(h=>h.seat===seat);out[offset+11+i]=moves.filter(h=>h.check).length/8;out[offset+13+i]=moves.filter(h=>h.chased.length).length/8;}
  out[offset+15]=o.legalActions.length/90;
  return out;
}
export function verifyManifest(m:ModelManifest,o:Observation):void{
  if(m.schemaVersion!==1||m.rulesHash!==o.rulesHash||m.featureVersion!==FEATURE_VERSION||m.inputSize!==INPUT_SIZE||m.actionSize!==ACTION_SIZE||!/^([a-f0-9]{64})$/.test(m.sha256))throw new Error('模型与规则或特征版本不兼容');
}
export interface Evaluation { policy: Float32Array; value: number }
export type Evaluator=(observation:Observation)=>Promise<Evaluation>;
export function legalPolicy(o:Observation,logits:ArrayLike<number>):Map<string,number>{
  const values=o.legalActions.map(a=>logits[actionIndex(a)]??0);const max=Math.max(...values);
  const exps=values.map(x=>Math.exp(Math.max(-60,x-max))),sum=exps.reduce((a,b)=>a+b,0);
  return new Map(o.legalActions.map((a,i)=>[a.type==='flip'?`f${a.square}`:`m${a.from}:${a.to}`,exps[i]/sum]));
}
