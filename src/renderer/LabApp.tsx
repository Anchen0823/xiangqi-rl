import { useCallback, useEffect, useRef, useState } from 'react';
import type { Action, Mode, ModelManifest, Observation, PieceDefinition, Scenario, SearchResult, Seat, SavedVariant, Movement } from '../variants/types';
import { actionKey } from '../variants/types';
import { makeScenario, rulesHash, squareName, validateScenario } from '../variants/rules';
import './lab.css';

interface Snapshot { observation:Observation; practice:boolean; totalPlies:number }
type WorkerReply={id:number;ok:boolean;data:unknown;error?:string};
function client(worker:Worker){let id=0;const pending=new Map<number,{resolve:(x:any)=>void;reject:(e:Error)=>void}>();worker.onmessage=(event:MessageEvent<WorkerReply>)=>{const r=event.data,p=pending.get(r.id);if(p){pending.delete(r.id);r.ok?p.resolve(r.data):p.reject(new Error(r.error));}};worker.onerror=e=>{for(const p of pending.values())p.reject(new Error(e.message));pending.clear();};return {call:<T,>(method:string,params:unknown={})=>new Promise<T>((resolve,reject)=>{pending.set(++id,{resolve,reject});worker.postMessage({id,method,params});}),close:()=>{worker.terminate();for(const p of pending.values())p.reject(new Error('已取消'));pending.clear();}};}
type Client=ReturnType<typeof client>;
const labels:Record<string,string>={k:'将',a:'士',b:'象',n:'马',r:'车',c:'炮',p:'兵',q:'后'};
const resultLabels:Record<string,string>={checkmate:'将死',stalemate:'无合法动作',all_captured:'棋子全部被吃',natural_limit:'自然限着和棋',mutual_repetition:'双方循环和棋',perpetual_check:'长将判负',perpetual_chase:'长捉判负'};
const modes:{id:Mode;title:string;description:string}[]=[{id:'custom',title:'变体实验室',description:'组合走法 · 子力实验'},{id:'jieqi',title:'揭棋',description:'先走后揭 · 私有信息'},{id:'banqi',title:'翻棋',description:'4 × 8 · 炮可打暗子'}];
const presets=[['queen-left-3','左后对三车'],['queen-right-3','右后对三车'],['queen-left-2','左后对双车'],['queen-right-2','右后对双车'],['ending-2','少子 · 后对双车'],['ending-3','少子 · 后对三车'],['standard','标准摆法']];
function download(name:string,data:unknown){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function pieceLabel(o:Observation,p:Observation['pieces'][number]){if(p.hidden)return '暗';if(p.color==='red'&&p.kind==='k')return '帅';return o.rules.pieces.find(d=>d.id===p.kind)?.label??'?';}
const defaultDefinition:PieceDefinition={id:'x',label:'新',moves:[{directions:[[1,0],[-1,0],[0,1],[0,-1]],max:1}],captures:[{directions:[[1,0],[-1,0],[0,1],[0,-1]],max:1}]};
export function LabApp({initialMode='custom'}:{initialMode?:Mode}){
  type ModelSource={manifest:ModelManifest;bytes:ArrayBuffer;name:string;note:string};
  const manualModel=useRef<ModelSource|null>(null),modelLoads=useRef(new WeakMap<Client,{hash:string;promise:Promise<void>}>());
  const [modelNote,setModelNote]=useState('尚未提供匹配规则的权重，使用基础搜索'),[workerVersion,setWorkerVersion]=useState(0);
  const referee=useRef<Client|null>(null),engine=useRef<Client|null>(null),epoch=useRef(0),busyRef=useRef(false);
  const [snapshot,setSnapshot]=useState<Snapshot|null>(null),[mode]=useState<Mode>(initialMode),[preset,setPreset]=useState('queen-left-3');
  const [playerMode,setPlayerMode]=useState<'ai'|'local'>('ai'),[human,setHuman]=useState<Seat>(0),[nodes,setNodes]=useState(128),[seed,setSeed]=useState(20261002);
  const [selected,setSelected]=useState<number|null>(null),[flipped,setFlipped]=useState(false),[busy,setBusy]=useState(false),[auto,setAuto]=useState(true),[error,setError]=useState(''),[metrics,setMetrics]=useState<SearchResult|null>(null);
  const [curtain,setCurtain]=useState(false),[tab,setTab]=useState<'rules'|'editor'|'training'|'report'>('rules'),[draft,setDraft]=useState<Scenario|null>(null),[tool,setTool]=useState('red:q'),[modelName,setModelName]=useState('基础搜索'),[replay,setReplay]=useState(false),[report,setReport]=useState<any>(null);
  const [receipt,setReceipt]=useState<{seat:Seat;label:string}|null>(null);
  const [definition,setDefinition]=useState<PieceDefinition>(structuredClone(defaultDefinition));
  const [group,setGroup]=useState({kind:'orthogonal',distance:0,target:'both',region:'all',screens:0,dx:2,dy:1,bx:1,by:0,blocked:false});
  const fileInput=useRef<HTMLInputElement>(null),modelInput=useRef<HTMLInputElement>(null),reportInput=useRef<HTMLInputElement>(null);
  const observation=snapshot?.observation;
  const startEngine=useCallback(()=>{engine.current?.close();engine.current=client(new Worker(new URL('../variants/search-worker.ts',import.meta.url),{type:'module'}));setModelName('正在检查模型…');setWorkerVersion(v=>v+1);},[]);
  const prepareModel=useCallback((o:Observation,target:Client):Promise<void>=>{
    const hash=rulesHash(o.rules),cached=modelLoads.current.get(target);
    if(cached?.hash===hash)return cached.promise;
    const promise=(async()=>{
      await cached?.promise.catch(()=>{});
      let source=manualModel.current?.manifest.rulesHash===hash?manualModel.current:null;
      try{
        if(!source&&window.desktopModels){
          const bundled=await window.desktopModels.load(mode,hash);
          if(bundled)source={manifest:bundled.manifest as ModelManifest,bytes:new Uint8Array(bundled.bytes).buffer,name:bundled.model.name,note:bundled.model.note};
        }
        if(engine.current!==target)return;
        if(source){await target.call('model',{manifest:source.manifest,bytes:source.bytes,observation:o});if(engine.current===target){setModelName(source.name);setModelNote(source.note);}}
        else{await target.call('clearModel');if(engine.current===target){setModelName('模型空位 · 基础搜索');setModelNote('尚未训练或没有匹配当前规则的权重');}}
      }catch(e){if(engine.current===target){await target.call('clearModel');setModelName('模型不可用 · 基础搜索');setModelNote(String(e));}}
    })();
    modelLoads.current.set(target,{hash,promise});return promise;
  },[mode]);
  const activeRulesHash=observation?rulesHash(observation.rules):'';
  useEffect(()=>{if(observation&&engine.current)void prepareModel(observation,engine.current);},[activeRulesHash,workerVersion,prepareModel]);
  const cancel=useCallback(()=>{epoch.current++;busyRef.current=false;setBusy(false);startEngine();},[startEngine]);
  const viewer=playerMode==='local'?'turn':human;
  const accept=(s:Snapshot)=>{setSnapshot(s);setSelected(null);setError('');};
  const reset=useCallback(async(scenario?:Scenario)=>{cancel();setReplay(false);setDraft(null);setCurtain(false);setReceipt(null);setMetrics(null);try{const s=await referee.current!.call<Snapshot>('new',{scenario:scenario??makeScenario(mode,seed,preset),viewer:playerMode==='local'?'turn':human});accept(s);}catch(e){setError(String(e));}},[mode,preset,seed,playerMode,human,cancel]);
  useEffect(()=>{referee.current=client(new Worker(new URL('../variants/referee-worker.ts',import.meta.url),{type:'module'}));startEngine();void reset();return()=>{referee.current?.close();engine.current?.close();};},[]);
  useEffect(()=>{if(referee.current)void reset();},[mode,preset]);
  useEffect(()=>{if(!snapshot)return;cancel();setReceipt(null);void referee.current!.call<Snapshot>('view',{viewer}).then(accept).catch(e=>setError(String(e)));setCurtain(playerMode==='local'&&mode==='jieqi');},[playerMode,human]);
  const finishTurn=async(s:Snapshot,mover:Seat,previousCaptures:number)=>{
    if(playerMode==='local'&&mode==='jieqi'){
      const last=s.observation.captures.at(-1);
      if(s.observation.captures.length>previousCaptures&&last?.hidden){
        const own=await referee.current!.call<Snapshot>('view',{viewer:mover});
        const kind=own.observation.captures.at(-1)!.kind!;
        setReceipt({seat:mover,label:own.observation.rules.pieces.find(p=>p.id===kind)?.label??kind});accept(own);setCurtain(true);return;
      }
      setCurtain(s.observation.result.kind==='ongoing');
    }accept(s);
  };
  const commit=async(action:Action)=>{if(busyRef.current||!observation)return;busyRef.current=true;setBusy(true);try{const s=await referee.current!.call<Snapshot>('play',{action,viewer});await finishTurn(s,observation.turn,observation.captures.length);}catch(e){setError(String(e));}finally{busyRef.current=false;setBusy(false);}};
  const think=useCallback(async()=>{
    if(!observation||busyRef.current||draft||replay||observation.result.kind!=='ongoing')return;
    const generation=epoch.current;busyRef.current=true;setBusy(true);setError('');
    try{
      // Request the acting player's view, never forward referee state to the search worker.
      const s=await referee.current!.call<Snapshot>('view',{viewer:'turn'});
      const target=engine.current!;await prepareModel(s.observation,target);
      if(generation!==epoch.current)return;
      const result=await target.call<SearchResult>('search',{observation:s.observation,budget:{nodes,rollout:8,seed:700000+s.observation.ply*997,maxMillis:10000}});
      if(generation!==epoch.current)return;setMetrics(result);
      if(result.status==='timeout'){setError('达到10秒交互时限，未落子；可调低预算或重试。');setAuto(false);return;}
      if(result.action){const next=await referee.current!.call<Snapshot>('play',{action:result.action,viewer});if(generation===epoch.current)await finishTurn(next,s.observation.turn,s.observation.captures.length);}
    }catch(e){if(generation===epoch.current){setError(String(e));setAuto(false);}}
    finally{if(generation===epoch.current){busyRef.current=false;setBusy(false);}}
  },[observation,nodes,draft,replay,viewer,playerMode,mode,prepareModel]);
  useEffect(()=>{if(auto&&playerMode==='ai'&&observation&&observation.turn!==human&&!curtain&&!draft&&!replay&&!busy){const timer=setTimeout(()=>void think(),180);return()=>clearTimeout(timer);}},[auto,observation,playerMode,human,curtain,draft,replay,busy,think]);
  const shown=observation&&draft?{...observation,rules:draft.rules,pieces:draft.pieces,legalActions:[],turn:draft.turn,seats:draft.seats}:observation;
  const clickSquare=(sq:number)=>{
    if(draft){const next=structuredClone(draft);if(tool==='move'){if(selected===null){if(next.pieces.some(p=>p.square===sq))setSelected(sq);return;}const piece=next.pieces.find(p=>p.square===selected);if(piece){next.pieces=next.pieces.filter(p=>p.square!==sq||p.id===piece.id);piece.square=sq;}setSelected(null);}else{next.pieces=next.pieces.filter(p=>p.square!==sq);if(tool!=='erase'){const [color,kind]=tool.split(':');next.pieces.push({id:Math.max(-1,...next.pieces.map(p=>p.id))+1,color:color as 'red'|'black',kind,role:kind,hidden:false,square:sq});}}setDraft(next);return;}
    if(!observation||busy||curtain||replay||(playerMode==='ai'&&observation.turn!==human)||observation.result.kind!=='ongoing')return;
    const flip=observation.legalActions.find(a=>a.type==='flip'&&a.square===sq);if(flip){void commit(flip);return;}
    const move=observation.legalActions.find(a=>a.type==='move'&&a.from===selected&&a.to===sq);if(move){void commit(move);return;}
    setSelected(observation.legalActions.some(a=>a.type==='move'&&a.from===sq)?sq:null);
  };
  const edit=async()=>{cancel();setAuto(false);setReplay(false);if(mode!=='custom'){setError('暗棋随机布局按种子生成；组合棋子与自由摆棋在自定义明棋中编辑。');return;}const data=await referee.current!.call<SavedVariant>('save');const s=structuredClone(data.scenario);s.pieces=observation!.pieces.map(p=>({...p,color:p.color!,kind:p.kind!}));s.turn=observation!.turn;setDraft(s);setTab('editor');};
  const apply=()=>{if(!draft)return;try{validateScenario(draft);void reset(draft);}catch(e){setError(String(e));}};
  const addMovement=()=>{
    const dirs:Record<string,[number,number][]>={orthogonal:[[1,0],[-1,0],[0,1],[0,-1]],diagonal:[[1,1],[-1,1],[1,-1],[-1,-1]],leap:[[group.dx,group.dy]],forward:[[0,1]]};
    const movement:Movement={directions:dirs[group.kind],max:group.kind==='leap'?1:group.distance,region:group.region as Movement['region'],...(group.kind==='leap'?{jump:true,...(group.blocked?{blockers:[[group.bx,group.by]] as [number,number][]}:{})}:{}),...(group.kind==='forward'?{relative:true}:{}),...(group.target==='captures'?{screens:group.screens}:{})};
    setDefinition(d=>({...d,moves:group.target==='captures'?d.moves:[...d.moves,movement],captures:group.target==='moves'?d.captures:[...d.captures,movement]}));
  };
  const savePiece=()=>{if(!draft)return;const next=structuredClone(draft);next.rules.pieces=next.rules.pieces.filter(p=>p.id!==definition.id);next.rules.pieces.push(structuredClone(definition));try{validateScenario(next);setDraft(next);setTool(`red:${definition.id}`);setError('');}catch(e){setError(String(e));}};
  const uploadGame=async(file:File)=>{try{const data=JSON.parse(await file.text());const fileMode=data.scenario?.rules?.mode??data.rules?.mode;if(fileMode!==mode)throw new Error('棋谱属于另一种玩法，请先切换到对应的同级入口再载入。');if(data.format==='xqlab'){cancel();setReplay(false);setDraft(null);accept(await referee.current!.call<Snapshot>('load',{data,viewer}));}else if(data.rules&&data.pieces){await reset(data);}else throw new Error('请选择 .xqlab 棋谱或局面 JSON');}catch(e){setError(String(e));}};
  const uploadModel=async(files:FileList)=>{try{const json=[...files].find(f=>f.name.endsWith('.json')),onnx=[...files].find(f=>f.name.endsWith('.onnx'));if(!json||!onnx||!observation)throw new Error('请同时选择 candidate.json 与 candidate.onnx');const manifest=JSON.parse(await json.text()) as ModelManifest,bytes=await onnx.arrayBuffer(),target=engine.current!;await prepareModel(observation,target);const r=await target.call<{name:string}>('model',{manifest,bytes,observation});manualModel.current={manifest,bytes,name:`手动候选 ${r.name}`,note:'自行载入的实验模型'};setModelName(manualModel.current.name);setModelNote(manualModel.current.note);setError('');}catch(e){setError(String(e));}};
  const privateCaptures=curtain?[]:observation?.captures??[];
  const result=observation?.result;
  const status=draft?'编辑初始摆法':replay?'研究复盘 · 练习局':result?.kind==='draw'?'和棋':result?.kind==='win'?`席位 ${result.winner!+1} 获胜`:`席位 ${(observation?.turn??0)+1} 行棋`;
  const modeTitle=modes.find(m=>m.id===mode)!.title;
  useEffect(()=>{document.title=`弈境 · ${modeTitle}`;},[modeTitle]);
  return <div className="lab-root">
    <header className="lab-header"><a className="lab-brand" href="#standard"><span>弈</span><div><strong>弈境</strong><small>XIANGQI · PLAY & RESEARCH</small></div></a><nav aria-label="棋类模式"><a href="#standard">普通象棋</a><a className={mode==='custom'?'active':''} href="#lab">变体实验室</a><a className={mode==='jieqi'?'active':''} href="#jieqi">揭棋</a><a className={mode==='banqi'?'active':''} href="#banqi">翻棋</a></nav><span className="lab-local"><i/>本地运行</span></header>
    <main className="lab-main"><section className="lab-heading"><div><p className="lab-eyebrow">{mode==='custom'?'规则可以改变，证据需要保留。':mode==='jieqi'?'落子，揭晓，再重新判断。':'未知的棋子，也有可计算的机会。'}</p><h1>{modeTitle}</h1><p>{mode==='custom'?'自定义棋子与初始摆法，探索同等预算下的子力关系。':mode==='jieqi'?'首步依占位行棋，吃走暗子的身份仅自己知晓。': '4 × 8 半盘暗棋，首翻定阵营，炮可隔子打暗子。'}</p></div><span className="lab-tag">LAB V1 · 实验规则</span></section>
      <div className="lab-layout"><aside className="lab-panel lab-settings"><h2>对局设置 <span>01</span></h2>
        {mode==='custom'&&<label>初始摆法<select value={preset} onChange={e=>setPreset(e.target.value)}>{presets.map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>}
        <label>对弈方式<select value={playerMode} onChange={e=>setPlayerMode(e.target.value as 'ai'|'local')}><option value="ai">人机对弈</option><option value="local">本地双人</option></select></label>
        {playerMode==='ai'&&<label>我的席位<select value={human} onChange={e=>setHuman(Number(e.target.value) as Seat)}><option value="0">席位 1 · 先手</option><option value="1">席位 2 · 后手</option></select></label>}
        <label>每步搜索预算<select value={nodes} onChange={e=>setNodes(Number(e.target.value))}>{[32,128,512,1024,4096].map(n=><option key={n} value={n}>{n.toLocaleString()} 状态访问</option>)}</select></label>
        <label>布局种子<input type="number" value={seed} onChange={e=>setSeed(Number(e.target.value))}/></label>
        <button className="lab-primary" onClick={()=>void reset()}>开始新局 <span>↗</span></button><div className="lab-button-row"><button onClick={()=>fileInput.current?.click()}>载入</button><button onClick={()=>void referee.current!.call('save').then(s=>download('对局.xqlab',s))}>保存棋谱</button></div>
        <input ref={fileInput} hidden type="file" accept=".json,.xqlab" onChange={e=>{if(e.target.files?.[0])void uploadGame(e.target.files[0]);e.target.value='';}}/>
        <div className="lab-engine"><small>当前 AI</small><strong>{modelName}</strong><span>{modelNote}</span><span>{mode==='custom'?'蒙特卡洛搜索':'信息集蒙特卡洛搜索'} · 单线程</span><button onClick={()=>modelInput.current?.click()} disabled={busy}>载入训练候选</button><input ref={modelInput} hidden type="file" multiple accept=".json,.onnx" onChange={e=>{if(e.target.files)void uploadModel(e.target.files);e.target.value='';}}/></div>
        <p className="lab-fine">搜索节点表示计算预算，不代表棋力等级。暗棋 AI 仅获得自己应知的信息。</p>
      </aside>
      <section className="lab-play"><div className="lab-player"><span className="lab-avatar dark">{flipped?'一':'二'}</span><div><strong>席位 {flipped?1:2}</strong><small>{observation?.seats[flipped?0:1]==='red'?'红方':observation?.seats[flipped?0:1]==='black'?'黑方':'阵营待首翻决定'}</small></div><span className="lab-status">{busy?'AI 思考中…':status}</span></div>
        <div className={`lab-board-frame ${mode==='banqi'?'banqi':''}`}>
          {shown&&<div className={`lab-board ${mode==='banqi'?'banqi':''}`} style={{aspectRatio:`${shown.rules.width}/${shown.rules.height}`,gridTemplateColumns:`repeat(${shown.rules.width},1fr)`}}>
            {mode!=='banqi'&&<svg className="lab-lines" viewBox="0 0 900 1000" preserveAspectRatio="none" aria-hidden="true"><g fill="none" stroke="#886339" strokeWidth="1.5">{Array.from({length:10},(_,y)=><path key={y} d={`M50 ${50+y*100} H850`}/>)}{Array.from({length:9},(_,x)=><path key={x} d={x===0||x===8?`M${50+x*100} 50 V950`:`M${50+x*100} 50 V450 M${50+x*100} 550 V950`}/>)}<path d="M350 50 L550 250 M550 50 L350 250 M350 750 L550 950 M550 750 L350 950"/></g><g fill="#866137" fontSize="30" fontFamily="serif" textAnchor="middle"><text x="250" y="511">楚 河</text><text x="650" y="511">漢 界</text></g></svg>}
            {Array.from({length:shown.rules.width*shown.rules.height},(_,i)=>{const x=i%shown.rules.width,y=Math.floor(i/shown.rules.width),sq=flipped?y*shown.rules.width+shown.rules.width-1-x:(shown.rules.height-1-y)*shown.rules.width+x;
              const p=shown.pieces.find(p=>p.square===sq),destination=shown.legalActions.some(a=>a.type==='move'&&a.from===selected&&a.to===sq),last=observation?.history.at(-1)?.action;
              return <button key={sq} className={`lab-square ${p?'occupied':''} ${selected===sq?'selected':''} ${destination?'destination':''} ${last&&(last.type==='flip'?last.square===sq:last.to===sq)?'last':''}`} aria-label={`${squareName(sq,shown.rules.width)} ${p?pieceLabel(shown,p):'空位'}`} onClick={()=>clickSquare(sq)} disabled={busy||curtain||replay}>
                {p?<span className={`lab-stone ${p.color??''} ${p.hidden?'hidden':''}`}>{pieceLabel(shown,p)}</span>:<span className="lab-point"/>}<small>{squareName(sq,shown.rules.width)}</small>
              </button>;})}
          </div>}
          {curtain&&<div className="lab-curtain"><span>◇</span>{receipt?<><h3>席位 {receipt.seat+1} 的暗吃信息</h3><p>你吃到的是：<strong>{receipt.label}</strong></p><button className="lab-primary" onClick={()=>{setReceipt(null);void referee.current!.call<Snapshot>('view',{viewer:'turn'}).then(accept);}}>隐藏并交接</button></>:<><h3>请交给下一位棋手</h3><p>吃走暗子的身份，仅向吃子者显示。</p><button className="lab-primary" onClick={()=>setCurtain(false)}>我是席位 {(observation?.turn??0)+1}，查看局面</button></>}</div>}
        </div>
        <div className="lab-player bottom"><span className="lab-avatar red">{flipped?'二':'一'}</span><div><strong>席位 {flipped?2:1}</strong><small>{observation?.seats[flipped?1:0]==='red'?'红方':observation?.seats[flipped?1:0]==='black'?'黑方':'阵营待首翻决定'}</small></div><span className="lab-ply">{observation?.ply??0}<small> 半回合</small></span></div>
        <div className="lab-board-tools"><button onClick={()=>setFlipped(!flipped)}>↻ 翻转</button><button onClick={()=>void edit()}>✎ 摆棋</button><button disabled={busy||!observation?.ply} onClick={()=>{cancel();setAuto(false);void referee.current!.call<Snapshot>('undo',{viewer}).then(accept);}}>↶ 悔棋</button><button onClick={()=>{if(busy){cancel();setAuto(false);}else{setAuto(false);void think();}}}>{busy?'停止搜索':'AI 走一步'}</button></div>
        {playerMode==='ai'&&<label className="lab-check"><input type="checkbox" checked={auto} onChange={e=>setAuto(e.target.checked)}/> 自动回应</label>}
        {snapshot?.practice&&<p className="lab-fine">练习局 · 不纳入正式实验</p>}{result?.kind!=='ongoing'&&result&&<div className="lab-result">{status} · {resultLabels[result.reason]??result.reason}</div>}
        {error&&<div role="alert" className="lab-error">{error}</div>}
      </section>
      <aside className="lab-panel lab-record"><h2>对局观察 <span>02</span></h2><div className="lab-metrics"><div><strong>{metrics?.nodes.toLocaleString()??'—'}</strong><small>实际节点</small></div><div><strong>{metrics?`${Math.round(metrics.elapsedMs)} ms`:'—'}</strong><small>搜索耗时</small></div><div><strong>{metrics?.simulations??'—'}</strong><small>采样模拟</small></div><div><strong>{metrics?.inferences??'—'}</strong><small>模型推理</small></div></div>
        <div className="lab-quiet"><span>自然限着</span><b>{observation?.quiet??0} / {observation?.rules.quietLimit??120}</b><progress value={observation?.quiet??0} max={observation?.rules.quietLimit??120}/></div>
        <h3>吃子记录 <small>当前玩家视角</small></h3><div className="lab-captures">{privateCaptures.length?privateCaptures.map(c=><span key={c.id} className={c.color}>{c.kind?(labels[c.kind]??c.kind):'未知'}</span>):<small>{curtain?'交接中已隐藏':'尚无吃子'}</small>}</div>
        <h3>着法记录</h3><ol className="lab-moves">{observation?.history.map((h,i)=><li key={i}><span>{i+1}</span><b>{h.action.type==='flip'?`翻 ${squareName(h.action.square,observation.rules.width)}`:`${squareName(h.action.from,observation.rules.width)} → ${squareName(h.action.to,observation.rules.width)}`}</b><small>{h.check?'将军':h.revealed?'揭子':''}</small></li>)}</ol>
        <button onClick={()=>{cancel();setAuto(false);setReplay(true);void referee.current!.call<Snapshot>('omniscient',{viewer}).then(accept);}}>全知研究视角</button>
        {(snapshot?.totalPlies??0)>0&&<label>复盘至第 {observation?.ply} 手<input type="range" min="0" max={snapshot!.totalPlies} value={observation?.ply??0} onChange={e=>{cancel();setAuto(false);setReplay(true);void referee.current!.call<Snapshot>('replay',{ply:Number(e.target.value),viewer}).then(accept);}}/></label>}
      </aside></div>
      {mode==='custom'&&<section className="lab-workbench"><div className="lab-tabs">{[['rules','规则与实验'],['editor','棋子与摆法'],['training','训练工作流'],['report','实验报告']].map(([id,name])=><button key={id} className={tab===id?'active':''} onClick={()=>setTab(id as typeof tab)}>{name}</button>)}</div>
        {tab==='rules'&&<div className="lab-rule-grid"><article><span>01 / 行棋</span><h3>{modes.find(m=>m.id===mode)?.title}</h3><p>{mode==='custom'?'后可沿横、竖、斜线滑行，不能越子。保留将帅安全与困毙判负，可自由组合其他棋子走法。':mode==='jieqi'?'暗子首步按原始占位角色行棋，落子后翻明。明士可出宫、明象可过河。只有吃子者知道被吃暗子的身份。':'首翻决定阵营。炮隔恰好一子可吃任意明敌子或暗子；打到己方暗子也移除，身份向双方公开。'}</p></article><article><span>02 / 裁决</span><h3>循环也有责任</h3><p>第三次重复检查最近两个循环：单方长将优先判负，其次单方长捉；同级责任判和。棋子价格不参与长捉判断。这是 lab-v1 实验定义。</p></article><article><span>03 / 证据</span><h3>先记录，再下结论</h3><p>固定初始摆法、换色对局和搜索预算。弱引擎的胜率只是实验线索，50%附近的点估计不能证明“后等于三车”。</p><code>{observation?.rulesHash.slice(0,20)}</code></article></div>}
        {tab==='editor'&&<div className="lab-editor"><div><h3>自由摆棋</h3>{!draft?<><p>从当前明棋局面进入编辑，AI 将暂停。</p><button onClick={()=>void edit()}>编辑当前局面</button></>:<><label>摆棋工具<select value={tool} onChange={e=>{setTool(e.target.value);setSelected(null);}}><option value="move">移动棋子</option><option value="erase">删除棋子</option>{['red','black'].flatMap(c=>draft.rules.pieces.map(p=><option key={`${c}:${p.id}`} value={`${c}:${p.id}`}>{c==='red'?'红':'黑'}{p.label}</option>))}</select></label><label>先行席位<select value={draft.turn} onChange={e=>setDraft({...draft,turn:Number(e.target.value) as Seat})}><option value="0">席位1（红）</option><option value="1">席位2（黑）</option></select></label><div className="lab-button-row"><button onClick={()=>setDraft({...draft,pieces:[]})}>清空</button><button onClick={()=>setDraft(makeScenario('custom',seed,'standard'))}>标准布局</button><button onClick={()=>download('实验摆法.json',draft)}>导出摆法</button><button onClick={()=>setDraft(null)}>取消</button></div><button className="lab-primary" onClick={apply}>检查并应用</button></>}</div>
          <div><h3>组合棋子走法</h3><div className="lab-button-row"><label>编号<input value={definition.id} onChange={e=>setDefinition({...definition,id:e.target.value})}/></label><label>棋子字<input maxLength={4} value={definition.label} onChange={e=>setDefinition({...definition,label:e.target.value})}/></label></div>
          <div className="lab-form-grid"><label>方向<select value={group.kind} onChange={e=>setGroup({...group,kind:e.target.value})}><option value="orthogonal">横竖四向</option><option value="diagonal">斜向四向</option><option value="forward">己方前进</option><option value="leap">自定义向量 / 跳跃</option></select></label><label>步长（0为滑行）<input type="number" min="0" max="10" value={group.distance} onChange={e=>setGroup({...group,distance:Number(e.target.value)})}/></label><label>动作<select value={group.target} onChange={e=>setGroup({...group,target:e.target.value})}><option value="both">移动与吃子</option><option value="moves">仅移动</option><option value="captures">仅吃子</option></select></label><label>活动区域<select value={group.region} onChange={e=>setGroup({...group,region:e.target.value})}><option value="all">全棋盘</option><option value="home">己方河界内</option><option value="crossed">过河区域</option><option value="palace">己方九宫</option></select></label>{group.target==='captures'&&<label>隔子数量<input type="number" min="0" max="8" value={group.screens} onChange={e=>setGroup({...group,screens:Number(e.target.value)})}/></label>}{group.kind==='leap'&&<><label>横向偏移<input type="number" value={group.dx} onChange={e=>setGroup({...group,dx:Number(e.target.value)})}/></label><label>纵向偏移<input type="number" value={group.dy} onChange={e=>setGroup({...group,dy:Number(e.target.value)})}/></label><label className="lab-check"><input type="checkbox" checked={group.blocked} onChange={e=>setGroup({...group,blocked:e.target.checked})}/>检查蹩腿格</label>{group.blocked&&<><label>腿格横向偏移<input type="number" value={group.bx} onChange={e=>setGroup({...group,bx:Number(e.target.value)})}/></label><label>腿格纵向偏移<input type="number" value={group.by} onChange={e=>setGroup({...group,by:Number(e.target.value)})}/></label></>}</>}</div>
          <div className="lab-button-row"><button onClick={addMovement}>＋追加走法</button><button onClick={()=>setDefinition({...definition,moves:[],captures:[]})}>清空走法</button><button disabled={!draft} onClick={savePiece}>保存到当前规则</button></div><pre>{JSON.stringify(definition,null,2)}</pre></div></div>}
        {tab==='training'&&<div className="lab-rule-grid"><article><span>01 / 本机训练</span><h3>数据 → 训练 → 候选</h3><p>运行根目录“训练变体.cmd”。三模式分别生成8局训练和2局验证数据，训练100步，中断恢复并导出模型，最后执行配对验证赛。</p><p>标准象棋 NNUE 与变体模型分开保存。</p></article><article><span>02 / 载入试玩</span><h3>把结果放回棋盘</h3><p>同时选择模型目录中的 candidate.json 与 candidate.onnx。系统检查规则哈希、特征版本及模型内容哈希。</p><button onClick={()=>modelInput.current?.click()}>选择模型文件</button></article><article><span>03 / 验收边界</span><h3>训练成功 ≠ 棋力提升</h3><p>短训验证完整流水线。模型能力需要在独立种子、相同计算预算下与基线比较，不能由 loss 下降代替。</p></article></div>}
        {tab==='report'&&<div className="lab-report"><div><h3>把实验结果带回这里</h3><p>载入批量评测生成的 summary.json。配对统计保留先后手、颜色、未完成对局和不确定性。</p><button onClick={()=>reportInput.current?.click()}>载入实验报告</button><input hidden ref={reportInput} type="file" accept=".json" onChange={async e=>{try{const data=JSON.parse(await e.target.files![0].text());if(data.schemaVersion!==1||!data.config||!Array.isArray(data.allScheduledScoreBounds))throw new Error('不是实验报告');setReport(data);}catch(err){setError(String(err));}}}/></div>{report&&<div><h3>{report.config.id}</h3><p>完成 {report.games} / {report.scheduledGames} 局 · 胜 / 和 / 负：{report.wins} / {report.draws} / {report.losses}</p><p>得分率 {report.scoreRate===null?'暂无':`${(report.scoreRate*100).toFixed(1)}%`} · 95%区间 {report.score95?report.score95.map((n:number)=>`${(n*100).toFixed(1)}%`).join(' — '):'无整体区间'}</p><p>{report.warning}</p><pre>{JSON.stringify(report,null,2)}</pre></div>}</div>}
      </section>}<footer className="lab-footer"><span>{modeTitle} / 规则版本 lab-v1</span><span>可玩 · 可复现 · 保留不确定性</span></footer>
    </main>
  </div>;
}
