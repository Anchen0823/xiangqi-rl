import type { Action, GameState, Observation, SearchBudget, SearchResult, Seat } from './types';
import { actionIndex, actionKey } from './types';
import { determinize, legalActions, observe, play } from './rules';
import { Random } from './random';
import { legalPolicy, type Evaluator } from './features';

interface Edge { action:Action; visits:number; available:number; value:number; prior:number }
interface Node { visits:number; edges:Map<string,Edge> }
/** The key contains only information available to the actor, not a determinization. */
export function informationKey(o:Observation):string{
  return `${o.viewer}|${o.turn}|${o.seats}|${o.quiet}|${o.pieces.map(p=>`${p.id}:${p.square}:${p.kind??'?'}:${p.color??'?'}:${p.role}`).join(';')}|${o.captures.map(c=>`${c.id}:${c.color}:${c.kind??'?'}`).join(';')}|${o.keys.join('/')}|${o.history.map(h=>actionKey(h.action)).join(',')}`;
}
function resultValue(s:GameState,seat:Seat):number{return s.result.kind==='win'?(s.result.winner===seat?1:-1):0;}
export async function search(root:Observation,budget:SearchBudget,evaluate?:Evaluator):Promise<SearchResult>{
  if(!Number.isInteger(budget.nodes)||budget.nodes<1||budget.nodes>1_000_000||!Number.isInteger(budget.rollout)||budget.rollout<0||budget.rollout>128||!Number.isFinite(budget.seed))throw new Error('搜索预算无效');
  const begin=performance.now(),rng=new Random(budget.seed),trees=new Map<string,Node>();
  let nodes=1,simulations=0,inferences=0,timeout=false;
  const room=()=>{if(budget.maxMillis&&performance.now()-begin>=budget.maxMillis){timeout=true;return false;}return nodes<budget.nodes;};
  const answer=(action:Action|null,policy:[number,number][],status:SearchResult['status']):SearchResult=>({action,policy,nodes,simulations,inferences,elapsedMs:performance.now()-begin,status});
  if(!root.legalActions.length)return answer(null,[],'terminal');
  const create=async(o:Observation):Promise<{node:Node;value?:number}>=>{
    let priors:Map<string,number>|undefined,value:number|undefined;
    if(evaluate){const e=await evaluate(o);inferences++;if(!Number.isFinite(e.value)||e.policy.length!==8190||!e.policy.every(Number.isFinite))throw new Error('模型输出无效');priors=legalPolicy(o,e.policy);value=e.value;}
    return {node:{visits:0,edges:new Map(o.legalActions.map(a=>[actionKey(a),{action:a,visits:0,available:0,value:0,prior:priors?.get(actionKey(a))??1/o.legalActions.length}]))},value};
  };
  const rootKey=informationKey(root),rootNode=(await create(root)).node;trees.set(rootKey,rootNode);
  while(room()){
    // Each sampled return to the root is a state visit too. Child transitions
    // and rollout transitions below each charge one further visit.
    nodes++;
    let state=determinize(root,rng),value=0;
    const path:{node:Node;edge:Edge;seat:Seat}[]=[];
    let leaf=false;
    while(room()&&state.result.kind==='ongoing'){
      const o=observe(state,state.turn),key=informationKey(o);let node=trees.get(key);
      if(!node){const fresh=await create(o);node=fresh.node;trees.set(key,node);leaf=true;
        if(fresh.value!==undefined){value=state.turn===root.viewer?fresh.value:-fresh.value;break;}
      }
      if(leaf)break;
      const available=o.legalActions.map(a=>{const k=actionKey(a);if(!node!.edges.has(k))node!.edges.set(k,{action:a,visits:0,available:0,value:0,prior:1/o.legalActions.length});return node!.edges.get(k)!;});
      if(!available.length)break;
      for(const e of available)e.available++;
      // Own-player values at every observer's tree; hidden worlds never key an edge.
      const scored=available.map(edge=>({edge,score:edge.visits===0?1e6+edge.prior+rng.next()*1e-5:edge.value/edge.visits+Math.SQRT2*Math.sqrt(Math.log(edge.available+1)/edge.visits)+(evaluate?edge.prior*Math.sqrt(node!.visits+1)/(edge.visits+1):0)}));
      scored.sort((a,b)=>b.score-a.score);const edge=scored[0].edge;
      path.push({node,edge,seat:state.turn});state=play(state,edge.action,true);nodes++;
    }
    if(state.result.kind!=='ongoing')value=resultValue(state,root.viewer);
    else if(!evaluate){
      for(let step=0;step<budget.rollout&&room()&&state.result.kind==='ongoing';step++){
        const actions=legalActions(state);if(!actions.length)break;
        state=play(state,actions[rng.int(actions.length)],true);nodes++;
      }value=resultValue(state,root.viewer);
    }
    for(const {node,edge,seat}of path){node.visits++;edge.visits++;edge.value+=seat===root.viewer?value:-value;}
    simulations++;
    if(!path.length)break;
  }
  const edges=[...rootNode.edges.values()],total=edges.reduce((n,e)=>n+e.visits,0);
  const best=Math.max(...edges.map(e=>e.visits));const choices=edges.filter(e=>e.visits===best);
  const action=choices[rng.int(choices.length)].action;
  return answer(action,edges.map(e=>[actionIndex(e.action),total?e.visits/total:1/edges.length]),timeout?'timeout':'ok');
}
