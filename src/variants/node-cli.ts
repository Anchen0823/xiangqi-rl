import { createInterface } from 'node:readline';
import { readFile, writeFile, mkdir, rename } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve, join } from 'node:path';
import { InferenceSession, Tensor } from 'onnxruntime-node';
import type { Action, GameState, Mode, ModelManifest, Observation, Scenario } from './types';
import { actionIndex } from './types';
import { makeScenario, newGame, observe, play, rulesHash, squareName } from './rules';
import { search } from './search';
import { encode, verifyManifest, INPUT_SIZE, ACTION_SIZE, FEATURE_VERSION, type Evaluator } from './features';
import { saveVariant, loadVariant } from './storage';
import { playExperiment, reportHtml, schedule, summarize, type ExperimentConfig, type ExperimentRecord } from './experiment';
import { hash } from './random';

const models=new Map<string,{manifest:ModelManifest;evaluate:Evaluator}>();
const engineSource=await readFile(new URL(import.meta.url));
const executableHash=createHash('sha256').update(engineSource).digest('hex');
async function atomicWrite(path:string,data:string){
  await writeFile(path+'.tmp',data);
  // Windows readers and virus scanners can briefly deny replacement.
  for(let attempt=0;;attempt++)try{await rename(path+'.tmp',path);return;}
  catch(e){if(attempt>=20||!['EPERM','EACCES','EBUSY'].includes((e as NodeJS.ErrnoException).code??''))throw e;await new Promise(resolve=>setTimeout(resolve,100));}
}
async function model(file:string|undefined,o:Observation):Promise<Evaluator|undefined>{
  if(!file)return undefined;const path=resolve(file);
  if(!models.has(path)){
    const manifest=JSON.parse(await readFile(path.replace(/\.onnx$/i,'.json'),'utf8')) as ModelManifest;
    verifyManifest(manifest,o);const bytes=await readFile(path);
    if(createHash('sha256').update(bytes).digest('hex')!==manifest.sha256)throw new Error('模型 SHA256 校验失败');
    const session=await InferenceSession.create(bytes,{intraOpNumThreads:1,interOpNumThreads:1,executionMode:'sequential',executionProviders:['cpu']});
    models.set(path,{manifest,evaluate:async(obs)=>{verifyManifest(manifest,obs);const outputs=await session.run({observation:new Tensor('float32',encode(obs),[1,INPUT_SIZE])});return {policy:outputs.policy.data as Float32Array,value:Number(outputs.value.data[0])};}});
  }
  const entry=models.get(path)!;verifyManifest(entry.manifest,o);return entry.evaluate;
}
function sparse(o:Observation):[number,number][]{const x=encode(o);return Array.from(x).flatMap((v,i)=>v?[[i,v] as [number,number]]:[]);}
let game:GameState|undefined;
async function codeHash():Promise<string>{
  return executableHash;
}
async function rpc(method:string,p:Record<string,any>):Promise<unknown>{
  if(method==='info'){const scenario=p.scenario??makeScenario(p.mode??'custom',p.seed??1,p.preset??'queen-left-3');newGame(scenario);return {scenario,rulesHash:rulesHash(scenario.rules),inputSize:INPUT_SIZE,actionSize:ACTION_SIZE,featureVersion:FEATURE_VERSION,codeHash:await codeHash()};}
  if(method==='new'){game=newGame(p.scenario??makeScenario(p.mode??'custom',p.seed??1,p.preset??'queen-left-3'));return observe(game,game.turn);}
  if(method==='load'){game=loadVariant(p.data);return observe(game,game.turn);}
  if(method==='step'){if(!game)throw new Error('先开始新局');game=play(game,p.action);return observe(game,game.turn);}
  if(method==='save'){if(!game)throw new Error('没有棋局');return saveVariant(game);}
  if(method==='analyze'){if(!game)throw new Error('没有棋局');const o=observe(game,game.turn);return search(o,{nodes:p.nodes??128,seed:p.seed??1,rollout:p.rollout??8,maxMillis:p.maxMillis},await model(p.model,o));}
  if(method==='evaluate'){if(!game)throw new Error('没有棋局');const o=observe(game,game.turn),fn=await model(p.model,o);if(!fn)throw new Error('缺少模型');const out=await fn(o);return {policy:Array.from(out.policy),value:out.value,features:Array.from(encode(o))};}
  if(method==='selfplay'){
    let state=newGame(p.scenario??makeScenario(p.mode??'custom',p.seed??1,p.preset??'queen-left-3'));
    const rows:unknown[]=[];const fn=await model(p.model,observe(state,state.turn));let nodes=0;
    while(state.result.kind==='ongoing'&&state.ply<(p.maxPlies??1000)){
      const o=observe(state,state.turn),result=await search(o,{nodes:p.nodes??32,seed:((p.agentSeed??12345)+state.ply*997)>>>0,rollout:p.rollout??4},fn);
      if(!result.action)throw new Error('搜索没有着法');nodes+=result.nodes;
      rows.push({x:sparse(o),legal:o.legalActions.map(actionIndex),pi:result.policy,seat:state.turn});state=play(state,result.action);
    }
    return {rulesHash:rulesHash(state.scenario.rules),seed:p.seed,agentSeed:p.agentSeed,result:state.result,status:state.result.kind==='ongoing'?'truncated':'complete',plies:state.ply,nodes,rows:state.result.kind==='ongoing'?[]:rows,game:saveVariant(state)};
  }
  if(method==='match'){
    const scenario:Scenario=p.scenario??makeScenario(p.mode??'custom',p.seed??1,p.preset??'queen-left-3');
    const config=p.config as ExperimentConfig,legs=schedule(scenario,config,p.group),leg=legs[p.leg];
    const o=observe(newGame(leg.scenario),0);
    return playExperiment(leg.scenario,config,p.group,p.leg,leg.seat,[await model(p.model,o),await model(p.opponent,o)]);
  }
  if(method==='report'){
    const out=resolve(p.out);await mkdir(out,{recursive:true});const summary=summarize(p.records,p.config,p.groupSize);
    await atomicWrite(join(out,'summary.json'),JSON.stringify(summary,null,2));await atomicWrite(join(out,'report.html'),reportHtml(summary,p.records));
    const csv=['id,group,leg,status,winner,reason,plies,nodes',...p.records.map((r:ExperimentRecord)=>[r.id,r.group,r.leg,r.status,r.result.winner??'',r.result.reason,r.actions.length,r.searches.reduce((n,s)=>n+s.nodes,0)].map(x=>`"${String(x).replaceAll('"','""')}"`).join(','))].join('\n');await writeFile(join(out,'games.csv'),'\ufeff'+csv);
    return summary;
  }
  if(method==='legal'){if(!game)throw new Error('没有棋局');return observe(game,game.turn).legalActions.map(a=>a.type==='move'?squareName(a.from)+squareName(a.to):`flip:${a.square}`);}
  throw new Error(`未知方法 ${method}`);
}
async function batch(){
  const args=new Map<string,string>();for(let i=3;i<process.argv.length;i+=2)args.set(process.argv[i].replace(/^--/,''),process.argv[i+1]);
  const mode=(args.get('mode')??'custom') as Mode,preset=args.get('preset')??'queen-left-3',out=resolve(args.get('out')??'reports/variants/pilot');await mkdir(out,{recursive:true});
  const source=args.get('scenario')?JSON.parse(await readFile(args.get('scenario')!,'utf8')):undefined;
  const suppliedScenario:Scenario|undefined=source?.format==='xqlab'?source.scenario:source;
  if(suppliedScenario&&suppliedScenario.rules.mode!==mode)throw new Error('导入局面的模式与 --mode 不一致');
  if(suppliedScenario)newGame(suppliedScenario);
  const modelPath=args.get('model'),opponentPath=args.get('opponent')??(mode==='custom'?modelPath:undefined);
  const mhash=async(p:string|undefined)=>p?createHash('sha256').update(await readFile(p)).digest('hex'):null;
  const config:ExperimentConfig={schemaVersion:1,id:`${mode}-${suppliedScenario?.id??preset}`,pairs:Number(args.get('pairs')??16),nodes:Number(args.get('nodes')??1024),rollout:Number(args.get('rollout')??8),seed:Number(args.get('seed')??42000),maxPlies:Number(args.get('max-plies')??1000),purpose:args.get('purpose')==='candidate'?'candidate':'material',codeHash:await codeHash(),modelHashes:[await mhash(modelPath),await mhash(opponentPath)],...(suppliedScenario?{scenarioHash:hash(suppliedScenario)}:{})};
  const configFile=join(out,'config.json');let prior:ExperimentConfig|undefined;try{prior=JSON.parse(await readFile(configFile,'utf8'));}catch(e){if((e as NodeJS.ErrnoException).code!=='ENOENT')throw e;}
  if(prior&&hash(prior)!==hash(config))throw new Error('恢复目录的配置不同；请指定新输出目录');
  await atomicWrite(configFile,JSON.stringify(config,null,2));await writeFile(join(out,'engine.mjs'),engineSource);const records:ExperimentRecord[]=[];
  for(let group=0;group<config.pairs;group++){
    const scenario=suppliedScenario??makeScenario(mode,config.seed+group,preset);const legs=schedule(scenario,config,group);
    for(const item of legs){const file=join(out,`game-${String(group).padStart(4,'0')}-${item.leg}.json`);let record:ExperimentRecord;
      try{record=JSON.parse(await readFile(file,'utf8'));if(record.configHash!==hash(config)||record.group!==group||record.leg!==item.leg||hash(record.scenario)!==hash(item.scenario))throw new Error('存档配置或初始摆法不匹配');}
      catch(e){if((e as NodeJS.ErrnoException).code!=='ENOENT')throw e;record=await rpc('match',{scenario,config,group,leg:item.leg,model:modelPath,opponent:opponentPath}) as ExperimentRecord;await atomicWrite(file,JSON.stringify(record));}
      records.push(record);await rpc('report',{out,config,records,groupSize:legs.length});
      process.stdout.write(`${group+1}/${config.pairs} leg ${item.leg+1}: ${record.status} ${record.result.reason}, ${record.actions.length} plies\n`);
    }
  }
}
if(process.argv[2]==='rpc'){
  const rl=createInterface({input:process.stdin,crlfDelay:Infinity});for await(const line of rl){try{const r=JSON.parse(line);const data=await rpc(r.method,r.params??{});process.stdout.write(JSON.stringify({id:r.id,ok:true,data})+'\n');}catch(e){process.stdout.write(JSON.stringify({ok:false,error:e instanceof Error?e.stack:String(e)})+'\n');}}
}else if(process.argv[2]==='batch')await batch();
else if(process.argv[2]==='benchmark'){
  for(const mode of ['custom','jieqi','banqi'] as const){const o=observe(newGame(makeScenario(mode,1)),0);const r=await search(o,{nodes:1024,rollout:8,seed:1});process.stdout.write(JSON.stringify({mode,...r,policy:undefined})+'\n');}
}else{process.stdout.write('Usage: node build/variants/cli.mjs rpc | batch --mode custom --preset queen-left-3 --nodes 1024 --pairs 16 --out reports/variants/pilot | benchmark\n');}
