import type { GameState, SavedVariant } from './types';
import { newGame, play, rulesHash } from './rules';
export function saveVariant(state:GameState):SavedVariant{return {schemaVersion:1,format:'xqlab',rulesHash:rulesHash(state.scenario.rules),scenario:state.scenario,actions:state.history.map(h=>h.action),practice:state.practice};}
export function loadVariant(data:SavedVariant,until=data.actions.length):GameState{
  if(data.schemaVersion!==1||data.format!=='xqlab'||!Array.isArray(data.actions)||data.actions.length>10000||data.rulesHash!==rulesHash(data.scenario.rules))throw new Error('棋谱版本、规则哈希或动作列表无效');
  let s=newGame(data.scenario);for(const a of data.actions.slice(0,until))s=play(s,a);s.practice=data.practice||until<data.actions.length;return s;
}
