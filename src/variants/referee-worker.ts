import type { GameState, SavedVariant, Seat } from './types';
import { newGame, observe, play } from './rules';
import { loadVariant, saveVariant } from './storage';
let state:GameState|undefined;
let saved:SavedVariant|undefined;
self.onmessage=(event:MessageEvent)=>{
  const {id,method,params:p={}}=event.data;
  try{
    if(method==='new'){state=newGame(p.scenario);saved=saveVariant(state);}
    else if(method==='play'){if(!state)throw new Error('没有棋局');state=play(state,p.action);saved=saveVariant(state);}
    else if(method==='load'){state=loadVariant(p.data);saved=p.data;}
    else if(method==='save'){if(!state)throw new Error('没有棋局');self.postMessage({id,ok:true,data:saveVariant(state)});return;}
    else if(method==='undo'){if(!state||!state.history.length)throw new Error('没有可悔棋着法');const data=saveVariant(state);data.actions.pop();data.practice=true;state=loadVariant(data);saved=data;}
    else if(method==='replay'){if(!saved)throw new Error('没有棋谱');state=loadVariant(saved,p.ply);state.practice=true;}
    else if(method==='omniscient'){if(!state)throw new Error('没有棋局');state.practice=true;}
    else if(method!=='view')throw new Error('未知裁判请求');
    if(!state)throw new Error('没有棋局');
    const viewer:Seat=p.viewer==='turn'?state.turn:p.viewer??0;
    const observation=observe(state,viewer);
    if(method==='omniscient'){observation.pieces=state.pieces.map(piece=>({...piece,hidden:false}));observation.captures=state.captures.map(c=>({...c}));observation.legalActions=[];}
    self.postMessage({id,ok:true,data:{observation,practice:state.practice,totalPlies:saved?.actions.length??state.ply}});
  }catch(e){self.postMessage({id,ok:false,error:e instanceof Error?e.message:String(e)});}
};
