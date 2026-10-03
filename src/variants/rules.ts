import type { Action, Capture, Color, GameResult, GameState, Mode, Movement, Observation, Piece, PieceDefinition, RuleSet, Scenario, Seat, TurnRecord } from './types';
import { actionKey, opposite, other } from './types';
import { canonical, hash, Random } from './random';

const orthogonal: [number,number][] = [[1,0],[-1,0],[0,1],[0,-1]];
const diagonal: [number,number][] = [[1,1],[-1,1],[1,-1],[-1,-1]];
const ongoing = (): GameResult => ({ kind: 'ongoing', reason: '' });
const def = (id: string, label: string, moves: Movement[], captures = moves): PieceDefinition => ({ id, label, moves, captures });
export function createRules(mode: Mode): RuleSet {
  const horses: Movement[] = [[1,2],[-1,2],[1,-2],[-1,-2],[2,1],[2,-1],[-2,1],[-2,-1]].map(([x,y]) => ({directions:[[x,y]],max:1,jump:true,blockers:[[Math.abs(x)===2?Math.sign(x):0,Math.abs(y)===2?Math.sign(y):0]]}));
  const elephants: Movement[] = diagonal.map(([x,y]) => ({directions:[[x*2,y*2]],max:1,jump:true,blockers:[[x,y]],region:'home'}));
  return {schemaVersion:1,version:'lab-v1',mode,width:mode==='banqi'?4:9,height:mode==='banqi'?8:10,quietLimit:mode==='banqi'?40:120,pieces:[
    def('k','将',[{directions:orthogonal,max:1,region:'palace'}]),
    def('a','士',[{directions:diagonal,max:1,region:'palace'}]),
    def('b','象',elephants), def('n','马',horses),
    def('r','车',[{directions:orthogonal,max:0}]),
    def('c','炮',[{directions:orthogonal,max:0}],[{directions:orthogonal,max:0,screens:1}]),
    def('p','兵',[{directions:[[0,1]],relative:true,max:1},{directions:[[1,0],[-1,0]],max:1,region:'crossed'}]),
    def('q','后',[{directions:[...orthogonal,...diagonal],max:0}]),
  ]};
}
const hashes = new WeakMap<RuleSet,string>();
export function rulesHash(rules: RuleSet): string { let h=hashes.get(rules); if(!h){h=hash(rules);hashes.set(rules,h);}return h; }
export const squareName = (s: number, width=9) => `${String.fromCharCode(97+s%width)}${Math.floor(s/width)}`;
export function square(text: string, width=9): number { return (Number(text.slice(1))*width)+(text.charCodeAt(0)-97); }
export function standardPieces(): Piece[] {
  const pieces: Piece[]=[];
  const put=(color:Color,kind:string,x:number,y:number)=>pieces.push({id:pieces.length,color,kind,role:kind,hidden:false,square:y*9+x});
  for(const color of ['red','black'] as const){const y=(n:number)=>color==='red'?n:9-n;
    [...'rnbakabnr'].forEach((k,x)=>put(color,k,x,y(0)));
    [1,7].forEach(x=>put(color,'c',x,y(2)));[0,2,4,6,8].forEach(x=>put(color,'p',x,y(3)));
  } return pieces;
}
export function makeScenario(mode:Mode, seed=1, preset='queen-left-3'): Scenario {
  const rules=createRules(mode), rng=new Random(seed);
  let pieces=standardPieces();
  const names: Record<string,string>={'queen-left-3':'左后对三车 · 全阵容','queen-right-3':'右后对三车 · 全阵容','queen-left-2':'左后对双车 · 全阵容','queen-right-2':'右后对双车 · 全阵容','ending-2':'后对双车 · 少子','ending-3':'后对三车 · 少子','standard':'标准摆法 · 实验裁决'};
  if(mode==='custom'&&preset!=='standard'){
    if(preset.startsWith('ending')) {
      pieces=[['k','red','d0'],['q','red','e2'],['k','black','f9'],['r','black','a9'],['r','black','i9'],...(preset.endsWith('3')?[['r','black','e7']]:[])].map(([kind,color,pos],id)=>({id,color:color as Color,kind,role:kind,hidden:false,square:square(pos)}));
    } else {
      if(!names[preset])throw new Error('未知预设');
      pieces=pieces.filter(p=>!(p.color==='red'&&p.kind==='r'));
      pieces.push({id:32,color:'red',kind:'q',role:'q',hidden:false,square:preset.includes('right')?8:0});
      if(preset.endsWith('3'))pieces.push({id:33,color:'black',kind:'r',role:'r',hidden:false,square:square('e8')});
    }
  }
  if(mode==='jieqi')for(const color of ['red','black'] as const){const own=pieces.filter(p=>p.color===color&&p.kind!=='k');const kinds=rng.shuffle(own.map(p=>p.kind));own.forEach((p,i)=>{p.kind=kinds[i];p.hidden=true;});}
  if(mode==='banqi'){pieces=rng.shuffle(pieces).map((p,id)=>({...p,id,square:id,hidden:true,role:'?'}));}
  return {schemaVersion:1,id:mode==='custom'?preset:mode,name:mode==='custom'?names[preset]:mode==='jieqi'?'揭棋 · 私有暗吃':'翻棋 · 炮可打暗子',rules,pieces,turn:0,seats:mode==='banqi'?[null,null]:['red','black'],focusColor:mode==='custom'?'red':undefined};
}
export function mirrorScenario(scenario: Scenario, swapColors=true): Scenario {
  const s=structuredClone(scenario), size=s.rules.width*s.rules.height;
  s.pieces=s.pieces.map(p=>({...p,square:size-1-p.square,color:swapColors?opposite(p.color):p.color}));
  if(swapColors&&s.focusColor)s.focusColor=opposite(s.focusColor);
  return s;
}
export function validateRules(r: RuleSet): void {
  if(r.schemaVersion!==1||r.version!=='lab-v1'||!['custom','jieqi','banqi'].includes(r.mode))throw new Error('不支持的规则版本');
  if(r.width!==(r.mode==='banqi'?4:9)||r.height!==(r.mode==='banqi'?8:10))throw new Error('棋盘尺寸不符合模式');
  if(r.quietLimit!==(r.mode==='banqi'?40:120))throw new Error('lab-v1 自然限着参数不可更改');
  if(!Array.isArray(r.pieces)||r.pieces.length>32)throw new Error('最多支持32种棋子');
  const ids=new Set<string>();
  for(const p of r.pieces){
    if(!/^[a-z][a-z0-9_]{0,15}$/.test(p.id)||ids.has(p.id)||!p.label||p.label.length>4)throw new Error('棋子编号或名称无效');ids.add(p.id);
    for(const groups of [p.moves,p.captures]){if(!Array.isArray(groups)||groups.length>32)throw new Error('走法组无效');for(const g of groups){
      if(!Number.isInteger(g.max)||g.max<0||g.max>10||!g.directions.length||g.directions.length>32)throw new Error('步长或方向无效');
      for(const [x,y] of [...g.directions,...g.blockers??[]])if(!Number.isInteger(x)||!Number.isInteger(y)||Math.abs(x)>9||Math.abs(y)>9||(!x&&!y))throw new Error('走法向量无效');
      if(g.screens!==undefined&&(!Number.isInteger(g.screens)||g.screens<0||g.screens>8))throw new Error('炮架数量无效');
      if(g.region&&!['all','palace','home','crossed'].includes(g.region))throw new Error('活动区域无效');
      if(g.max!==1&&g.blockers?.length)throw new Error('蹩腿只用于单次跳跃走法');
    }}
  }
  for(const id of ['k','a','b','n','r','c','p'])if(!ids.has(id))throw new Error('缺少基础棋子');
  const base=createRules(r.mode);
  for(const p of base.pieces.filter(p=>r.mode!=='custom'||p.id==='k'))if(canonical(r.pieces.find(x=>x.id===p.id))!==canonical(p))throw new Error('将帅及暗棋基础走法不可重定义');
}
export function validateScenario(s: Scenario): void {
  validateRules(s.rules);
  if(s.schemaVersion!==1||!Array.isArray(s.pieces)||!s.pieces.length||![0,1].includes(s.turn))throw new Error('局面格式无效');
  if(!Array.isArray(s.seats)||s.seats.length!==2||(!s.seats.every(x=>x===null)&&!(s.seats.includes('red')&&s.seats.includes('black'))))throw new Error('阵营配置无效');
  const ids=new Set<number>(),occupied=new Set<number>();
  for(const p of s.pieces){
    if(!Number.isInteger(p.id)||p.id<0||ids.has(p.id)||!Number.isInteger(p.square)||p.square<0||p.square>=s.rules.width*s.rules.height||occupied.has(p.square))throw new Error('棋子身份、位置重复或越界');
    if(!['red','black'].includes(p.color)||!s.rules.pieces.some(d=>d.id===p.kind)||typeof p.hidden!=='boolean')throw new Error('未知棋子');
    if(s.rules.mode!=='banqi'&&!s.rules.pieces.some(d=>d.id===p.role))throw new Error('未知占位角色');
    if(s.rules.mode==='custom'&&p.hidden)throw new Error('自定义明棋不能放暗子');
    ids.add(p.id);occupied.add(p.square);
  }
  if(s.rules.mode!=='banqi'){
    if(s.seats.includes(null))throw new Error('明棋与揭棋须指定双方颜色');
    for(const c of ['red','black'] as const){const kings=s.pieces.filter(p=>p.color===c&&p.kind==='k');if(kings.length!==1||kings[0].hidden||!inRegion(kings[0].square,c,'palace',s.rules))throw new Error('每方必须有一个九宫内的明将帅');}
    if(inCheck(s.pieces,s.seats[other(s.turn)]!,s.rules))throw new Error('非行棋方已被将军或将帅照面');
  }
}
export function newGame(scenario: Scenario): GameState {
  validateScenario(scenario);
  const s:GameState={scenario:structuredClone(scenario),pieces:structuredClone(scenario.pieces),captures:[],turn:scenario.turn,seats:[...scenario.seats],quiet:0,ply:0,result:ongoing(),history:[],keys:[],practice:false};
  s.keys=[positionKey(s)]; finishByMoves(s); return s;
}
function inRegion(to:number,color:Color,region:Movement['region'],r:RuleSet):boolean{
  const x=to%r.width,y=Math.floor(to/r.width),rank=color==='red'?y:r.height-1-y;
  return !region||region==='all'||(region==='palace'?x>=3&&x<=5&&rank<=2:region==='home'?rank<=4:rank>=5);
}
function effective(p:Piece):string{return p.hidden?p.role:p.kind;}
function banqiTargets(p:Piece,pieces:Piece[],r:RuleSet):number[]{
  if(p.hidden)return[];
  const board=new Map(pieces.map(x=>[x.square,x]));const out:number[]=[];const x=p.square%4,y=Math.floor(p.square/4);
  for(const [dx,dy]of orthogonal){let screens=0;
    for(let n=1;n<=8;n++){const a=x+dx*n,b=y+dy*n;if(a<0||a>=4||b<0||b>=8)break;const to=b*4+a,t=board.get(to);
      if(n===1&&!t)out.push(to);
      if(p.kind==='c'){if(t){if(screens===1){if(t.hidden||t.color!==p.color)out.push(to);break;}screens++;}}
      else{if(n===1&&t&&!t.hidden&&t.color!==p.color){const ranks=['p','c','n','r','b','a','k'];if(p.kind==='p'&&t.kind==='k'||p.kind!=='k'&&ranks.indexOf(p.kind)>=ranks.indexOf(t.kind)||p.kind==='k'&&t.kind!=='p')out.push(to);}break;}
    }
  }return out;
}
/** Pseudo attacks include the opposing king; public legal actions never capture a king. */
function targets(p:Piece,pieces:Piece[],r:RuleSet):number[]{
  if(r.mode==='banqi')return banqiTargets(p,pieces,r);
  const type=effective(p),definition=r.pieces.find(d=>d.id===type);if(!definition)return[];
  const out=new Set<number>(),board=new Map(pieces.map(x=>[x.square,x]));const x=p.square%r.width,y=Math.floor(p.square/r.width);
  for(const capture of [false,true])for(const group of capture?definition.captures:definition.moves){
    const region=r.mode==='jieqi'&&!p.hidden&&(type==='a'||type==='b')?'all':group.region;
    const relative=group.relative&&p.color==='black'?-1:1;
    for(const [vx,vy]of group.directions){const dx=vx,dy=vy*relative;let blocked=false;
      for(const [bx,by]of group.blockers??[]){const u=x+bx,v=y+by*relative;if(u<0||u>=r.width||v<0||v>=r.height||board.has(v*r.width+u)){blocked=true;break;}}
      if(blocked)continue;
      let screens=0;
      for(let n=1;n<=(group.max||Math.max(r.width,r.height));n++){
        const u=x+dx*n,v=y+dy*n;if(u<0||u>=r.width||v<0||v>=r.height)break;
        const to=v*r.width+u,t=board.get(to);
        if(inRegion(to,p.color,region,r)&&screens===(group.screens??0)&&((capture&&t&&t.color!==p.color)||(!capture&&!t)))out.add(to);
        if(t&&!group.jump){screens++;if(screens>(group.screens??0))break;}
      }
    }
  }
  if(type==='k'){const enemy=pieces.find(x=>x.color!==p.color&&effective(x)==='k');if(enemy&&enemy.square%r.width===x&&!pieces.some(t=>t.id!==p.id&&t.id!==enemy.id&&t.square%r.width===x&&t.square>Math.min(p.square,enemy.square)&&t.square<Math.max(p.square,enemy.square)))out.add(enemy.square);}
  return [...out];
}
export function inCheck(pieces:Piece[],color:Color,r:RuleSet):boolean{
  if(r.mode==='banqi')return false;
  const king=pieces.find(p=>p.color===color&&p.kind==='k'&&!p.hidden);if(!king)return true;
  const board=new Set(pieces.map(p=>p.square)),tx=king.square%r.width,ty=Math.floor(king.square/r.width);
  // Point attacks avoid generating every enemy move for every candidate king-safe move.
  for(const p of pieces){if(p.color===color)continue;const x=p.square%r.width,y=Math.floor(p.square/r.width),type=effective(p);
    if(type==='k'&&x===tx){let blocked=false;for(let row=Math.min(y,ty)+1;row<Math.max(y,ty);row++)if(board.has(row*r.width+x)){blocked=true;break;}if(!blocked)return true;}
    const d=r.pieces.find(d=>d.id===type);if(!d)continue;
    for(const g of d.captures){const region=r.mode==='jieqi'&&!p.hidden&&(type==='a'||type==='b')?'all':g.region;
      if(!inRegion(king.square,p.color,region,r))continue;
      const relative=g.relative&&p.color==='black'?-1:1;
      if(g.blockers?.some(([bx,by])=>{const u=x+bx,v=y+by*relative;return u<0||u>=r.width||v<0||v>=r.height||board.has(v*r.width+u);}))continue;
      for(const [dx,rawY]of g.directions){const dy=rawY*relative,n=dx?(tx-x)/dx:(ty-y)/dy;
        if(!Number.isInteger(n)||n<1||n>(g.max||Math.max(r.width,r.height))||x+dx*n!==tx||y+dy*n!==ty)continue;
        let screens=0;if(!g.jump)for(let step=1;step<n;step++)if(board.has((y+dy*step)*r.width+x+dx*step))screens++;
        if(screens===(g.screens??0))return true;
      }
    }
  }return false;
}
function movedPieces(pieces:Piece[],from:number,to:number,reveal=false):Piece[]{return pieces.filter(p=>p.square!==to).map(p=>p.square===from?{...p,square:to,hidden:reveal?false:p.hidden}:p);}
function legalCapture(p:Piece,target:Piece,pieces:Piece[],r:RuleSet):boolean{
  return targets(p,pieces,r).includes(target.square)&&(r.mode==='banqi'||!inCheck(movedPieces(pieces,p.square,target.square),p.color,r));
}
interface Geometry { to:number; blockers:number[]; path:number[]; screens:number; capture:boolean }
interface PieceGeometry { moves:Geometry[]; attacks:Map<number,Geometry[]> }
const geometries=new WeakMap<RuleSet,Map<string,PieceGeometry>>();
function geometry(p:Piece,r:RuleSet):PieceGeometry{
  let cache=geometries.get(r);if(!cache){cache=new Map();geometries.set(r,cache);}
  const type=effective(p),free=r.mode==='jieqi'&&!p.hidden&&(type==='a'||type==='b');
  const key=`${p.color}:${type}:${free}:${p.square}`;let data=cache.get(key);if(data)return data;
  data={moves:[],attacks:new Map()};const def=r.pieces.find(d=>d.id===type);if(!def)return data;
  const x=p.square%r.width,y=Math.floor(p.square/r.width);
  for(const capture of [false,true])for(const g of capture?def.captures:def.moves){const relative=g.relative&&p.color==='black'?-1:1;
    const blockers=(g.blockers??[]).map(([bx,by])=>{const u=x+bx,v=y+by*relative;return u<0||u>=r.width||v<0||v>=r.height?-1:v*r.width+u;});if(blockers.includes(-1))continue;
    for(const [dx,rawY]of g.directions){const dy=rawY*relative,path:number[]=[];
      for(let n=1;n<=(g.max||10);n++){const u=x+dx*n,v=y+dy*n;if(u<0||u>=r.width||v<0||v>=r.height)break;const to=v*r.width+u;
        if(inRegion(to,p.color,free?'all':g.region,r)){
          const entry={to,blockers,path:g.jump?[]:[...path],screens:g.screens??0,capture};data.moves.push(entry);
          if(capture){const options=data.attacks.get(to)??[];options.push(entry);data.attacks.set(to,options);}
        }path.push(to);
      }
    }
  }cache.set(key,data);return data;
}
function geometryClear(g:Geometry,board:(Piece|undefined)[]):boolean{
  for(const b of g.blockers)if(board[b])return false;
  let count=0;for(const b of g.path)if(board[b]){count++;if(count>g.screens)return false;}return count===g.screens;
}
function fastLegal(s:GameState,color:Color):Action[]{
  const r=s.scenario.rules,board:(Piece|undefined)[]=Array(r.width*r.height),out:Action[]=[];
  for(const p of s.pieces)board[p.square]=p;
  const king=s.pieces.find(p=>p.color===color&&effective(p)==='k')!;
  const enemies=s.pieces.filter(p=>p.color!==color).map(p=>({p,g:geometry(p,r)}));
  const safe=(kingSquare:number)=>{
    for(const {p,g}of enemies){if(board[p.square]!==p)continue;
      if(effective(p)==='k'&&p.square%r.width===kingSquare%r.width){let blocked=false;for(let at=Math.min(p.square,kingSquare)+r.width;at<Math.max(p.square,kingSquare);at+=r.width)if(board[at]){blocked=true;break;}if(!blocked)return false;}
      const threats=g.attacks.get(kingSquare);if(threats)for(const t of threats)if(geometryClear(t,board))return false;
    }return true;
  };
  for(const p of s.pieces){if(p.color!==color)continue;const seen=new Set<number>();
    for(const g of geometry(p,r).moves){if(seen.has(g.to))continue;const target=board[g.to];
      if(g.capture?(!target||target.color===color||effective(target)==='k'):Boolean(target))continue;
      if(!geometryClear(g,board))continue;
      board[p.square]=undefined;board[g.to]=p;
      const valid=safe(p===king?g.to:king.square);
      board[p.square]=p;board[g.to]=target;
      if(valid){seen.add(g.to);out.push({type:'move',from:p.square,to:g.to});}
    }
  }return out;
}
const legalCache=new WeakMap<GameState,{turn:Seat;pieces:Piece[];actions:Action[]}>();
export function legalActions(s:GameState,ignoreResult=false):Action[]{
  if(!ignoreResult&&s.result.kind!=='ongoing')return[];
  const cached=legalCache.get(s);if(cached&&cached.turn===s.turn&&cached.pieces===s.pieces)return cached.actions;
  const r=s.scenario.rules,color=s.seats[s.turn],out:Action[]=[];
  if(r.mode!=='banqi'&&color!==null){const actions=fastLegal(s,color);legalCache.set(s,{turn:s.turn,pieces:s.pieces,actions});return actions;}
  if(r.mode==='banqi')for(const p of s.pieces)if(p.hidden)out.push({type:'flip',square:p.square});
  if(color===null)return out;
  for(const p of s.pieces){if(p.color!==color||(r.mode==='banqi'&&p.hidden))continue;
    for(const to of targets(p,s.pieces,r)){
      const t=s.pieces.find(x=>x.square===to);
      if(r.mode!=='banqi'&&t?.kind==='k'&&!t.hidden)continue;
      if(r.mode==='banqi'||!inCheck(movedPieces(s.pieces,p.square,to),color,r))out.push({type:'move',from:p.square,to});
    }
  }return out;
}
/** Laboratory chase rule: legality and recapture, never material values or hidden identities. */
export function chaseTargets(before:Piece[],after:Piece[],movedId:number,color:Color,r:RuleSet):number[]{
  const result=new Set<number>();
  for(const p of after.filter(p=>p.color===color)){
    const pt=effective(p);if(r.mode==='banqi'&&p.hidden)continue;
    for(const t of after.filter(t=>t.color!==color)){
      if(r.mode==='banqi'&&t.hidden)continue;
      const tt=effective(t);
      if(r.mode!=='banqi'&&(tt==='k'||tt==='p'&&inRegion(t.square,t.color,'home',r)))continue;
      if(r.mode!=='banqi'&&p.id===movedId&&(pt==='k'||pt==='p'))continue;
      if(!legalCapture(p,t,after,r))continue;
      const oldP=before.find(x=>x.id===p.id),oldT=before.find(x=>x.id===t.id);
      if(oldP&&oldT&&legalCapture(oldP,oldT,before,r))continue; // unchanged static threat
      if(legalCapture(t,p,after,r))continue; // exchange invitation
      const captured=movedPieces(after,p.square,t.square);
      const attacker=captured.find(x=>x.id===p.id)!;
      if(captured.some(x=>x.color===t.color&&legalCapture(x,attacker,captured,r)))continue;
      result.add(t.id);
    }
  }return [...result].sort((a,b)=>a-b);
}
export function cycleResult(records:Pick<TurnRecord,'seat'|'check'|'chased'>[]):GameResult{
  const levels=[0,0];
  for(const seat of [0,1] as const){const moves=records.filter(x=>x.seat===seat);if(!moves.length)continue;
    if(moves.every(x=>x.check)){levels[seat]=2;continue;}
    const nonChecks=moves.filter(x=>!x.check);let intersection=new Set(nonChecks[0].chased);
    for(const m of nonChecks.slice(1))intersection=new Set([...intersection].filter(x=>m.chased.includes(x)));
    if(intersection.size)levels[seat]=1;
  }
  if(levels[0]===levels[1])return {kind:'draw',reason:'mutual_repetition'};
  const loser:Seat=levels[0]>levels[1]?0:1;return {kind:'win',winner:other(loser),reason:levels[loser]===2?'perpetual_check':'perpetual_chase'};
}
export function positionKey(s:GameState):string{
  // Reset at captures/revelations; within a reversible segment all knowledge is unchanged.
  return `${s.turn}|${s.seats.join(',')}|${s.pieces.map(p=>`${p.square},${p.hidden?'?'+p.role:p.kind},${s.scenario.rules.mode==='banqi'&&p.hidden?'?':p.color}`).sort().join(';')}`;
}
function finishByMoves(s:GameState):void{
  if(s.result.kind!=='ongoing')return;
  if(s.scenario.rules.mode==='banqi'&&s.seats[0])for(const seat of [0,1] as const)if(!s.pieces.some(p=>p.color===s.seats[seat])){s.result={kind:'win',winner:other(seat),reason:'all_captured'};return;}
  if(!legalActions(s,true).length)s.result={kind:'win',winner:other(s.turn),reason:s.seats[s.turn]&&inCheck(s.pieces,s.seats[s.turn]!,s.scenario.rules)?'checkmate':'stalemate'};
}
export function play(s:GameState,a:Action,checked=false):GameState{
  if(s.result.kind!=='ongoing')throw new Error('棋局已结束');
  if(!checked&&!legalActions(s).some(x=>actionKey(x)===actionKey(a)))throw new Error('非法着法');
  const n:GameState={...s,pieces:s.pieces.map(p=>({...p})),captures:[...s.captures],seats:[...s.seats],history:[...s.history],keys:[...s.keys],ply:s.ply+1,quiet:s.quiet+1,result:ongoing()};
  const r=s.scenario.rules,record:TurnRecord={seat:s.turn,action:a,check:false,chased:[]};
  const p=n.pieces.find(x=>x.square===(a.type==='flip'?a.square:a.from));if(!p)throw new Error('起点无棋子');
  if(a.type==='flip'){
    p.hidden=false;record.revealed={id:p.id,kind:p.kind,color:p.color};
    if(!n.seats[s.turn]){n.seats[s.turn]=p.color;n.seats[other(s.turn)]=opposite(p.color);}
  }else{
    const t=n.pieces.find(x=>x.square===a.to);
    if(t){const capture:Capture={id:t.id,color:t.color,kind:t.kind,role:t.role,hidden:t.hidden,by:s.turn};n.captures.push(capture);record.capture=capture;n.pieces=n.pieces.filter(x=>x.id!==t.id);}
    p.square=a.to;
    if(p.hidden){p.hidden=false;record.revealed={id:p.id,kind:p.kind,color:p.color};}
    record.check=inCheck(n.pieces,opposite(p.color),r);
    // A revelation/capture cannot occur in a reversible repetition segment.
    // Chase classification is expensive. Reconstruct the reversible segment only
    // when a third repetition actually needs adjudication (same exact rule).
  }
  n.turn=other(s.turn);n.history.push(record);
  const progress=Boolean(record.capture||record.revealed);
  if(progress){n.quiet=0;n.keys=[];}
  const key=positionKey(n);n.keys.push(key);
  // Mate / loss always wins over a draw counter on the same move.
  finishByMoves(n);
  if(n.result.kind==='ongoing'){
    const occurrences=n.keys.flatMap((x,i)=>x===key?[i]:[]);
    if(occurrences.length>=3){
      const start=occurrences[occurrences.length-3],length=n.keys.length-1-start,begin=n.history.length-length;
      let after=n.pieces;
      for(let i=n.history.length-1;i>=begin;i--){const entry={...n.history[i]},move=entry.action;
        if(move.type!=='move'||entry.revealed||entry.capture)throw new Error('循环片段包含不可逆动作');
        const moved=after.find(p=>p.square===move.to)!;
        const before=after.map(p=>p.id===moved.id?{...p,square:move.from}:p);
        if(!entry.check)entry.chased=chaseTargets(before,after,moved.id,moved.color,r);
        n.history[i]=entry;after=before;
      }
      n.result=cycleResult(n.history.slice(begin));
    }
    else if(n.quiet>=r.quietLimit)n.result={kind:'draw',reason:'natural_limit'};
  }
  return n;
}
export function observe(s:GameState,viewer:Seat):Observation{
  const inventory=new Map<string,{color:Color;kind:string;count:number}>();
  for(const p of s.scenario.pieces){const key=p.color+':'+p.kind;const item=inventory.get(key)??{color:p.color,kind:p.kind,count:0};item.count++;inventory.set(key,item);}
  return {schemaVersion:1,rules:s.scenario.rules,rulesHash:rulesHash(s.scenario.rules),viewer,
    pieces:s.pieces.map(p=>({...p,kind:p.hidden?null:p.kind,color:p.hidden&&s.scenario.rules.mode==='banqi'?null:p.color})),
    captures:s.captures.map(c=>({...c,kind:s.scenario.rules.mode==='jieqi'&&c.hidden&&c.by!==viewer?null:c.kind})),
    inventory:[...inventory.values()].sort((a,b)=>(a.color+':'+a.kind).localeCompare(b.color+':'+b.kind)),turn:s.turn,seats:[...s.seats],quiet:s.quiet,ply:s.ply,result:{...s.result},
    history:s.history.map(({capture:_,...record})=>record),keys:[...s.keys],legalActions:legalActions(s)};
}
/** Sample a complete world from this player's knowledge, including unknown captured identities. */
export function determinize(o:Observation,rng:Random):GameState{
  const pool=o.inventory.flatMap(x=>Array.from({length:x.count},()=>({kind:x.kind,color:x.color})));
  const take=(kind:string|null,color:Color|null)=>{
    const choices=pool.flatMap((p,i)=>(kind===null||p.kind===kind)&&(color===null||p.color===color)?[i]:[]);
    if(!choices.length)throw new Error('观测与棋子库存不一致');return pool.splice(choices[rng.int(choices.length)],1)[0];
  };
  // Consume all known entries before assigning unknowns; unknown graves are not discarded.
  const all=[...o.pieces.map(p=>({...p,dead:false})),...o.captures.map(p=>({...p,dead:true}))];
  const sampled=new Map<number,{kind:string;color:Color}>();
  for(const p of all.filter(p=>p.kind!==null))sampled.set(p.id,take(p.kind,p.color));
  for(const p of rng.shuffle(all.filter(p=>p.kind===null)))sampled.set(p.id,take(null,p.color));
  if(pool.length)throw new Error('观测遗漏棋子');
  const pieces=o.pieces.map(p=>({...p,...sampled.get(p.id)!}));
  const captures=o.captures.map(c=>({...c,...sampled.get(c.id)!}));
  const scenario:Scenario={schemaVersion:1,id:'sampled',name:'信息集样本',rules:o.rules,pieces:[...pieces,...captures.map(c=>({id:c.id,kind:c.kind,color:c.color,role:c.role,hidden:c.hidden,square:-1}))],turn:o.turn,seats:[...o.seats]};
  return {scenario,pieces,captures,turn:o.turn,seats:[...o.seats],quiet:o.quiet,ply:o.ply,result:{...o.result},history:o.history.map(h=>({...h})),keys:[...o.keys],practice:false};
}
