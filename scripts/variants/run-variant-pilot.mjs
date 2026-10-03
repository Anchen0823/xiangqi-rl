import { spawn } from 'node:child_process';
import { mkdir, readFile, writeFile, open, unlink } from 'node:fs/promises';
import { resolve, join } from 'node:path';
const root=resolve(process.argv[2]??'reports/variants/queen-pilot');
const engine=resolve(process.env.XQLAB_ENGINE??'build/variants/cli.mjs');
const concurrency=Number(process.env.XQLAB_JOBS??4);
if(!Number.isInteger(concurrency)||concurrency<1||concurrency>8)throw new Error('XQLAB_JOBS must be 1..8');
await mkdir(root,{recursive:true});
const lockPath=join(root,'run.lock');
try { const old=Number(await readFile(lockPath,'utf8'));let alive=false;try{process.kill(old,0);alive=true;}catch{}if(alive)throw new Error(`This experiment is already running (pid ${old})`);await unlink(lockPath); } catch(e) { if(e.code!=='ENOENT')throw e; }
const lock=await open(lockPath,'wx');await lock.writeFile(String(process.pid));await lock.close();
const jobs=['ending-2','ending-3','queen-left-2','queen-right-2','queen-left-3','queen-right-3'].flatMap(preset=>[1024,4096].map(nodes=>({preset,nodes,out:join(root,`${preset}-${nodes}`)})));
let cursor=0;
async function overview(){
  const entries=[];for(const j of jobs){try{entries.push({preset:j.preset,nodes:j.nodes,...JSON.parse(await readFile(join(j.out,'summary.json'),'utf8'))});}catch{entries.push({preset:j.preset,nodes:j.nodes,games:0,scheduledGames:32});}}
  await writeFile(join(root,'overview.json'),JSON.stringify(entries,null,2));
  const pct=n=>n===null||n===undefined?'—':`${(n*100).toFixed(1)}%`;
  await writeFile(join(root,'index.html'),`<!doctype html><meta charset="utf-8"><title>后与车 · 配对实验</title><style>body{font:16px system-ui;background:#f7f7ee;color:#244337;max-width:1200px;margin:50px auto;padding:20px}table{width:100%;border-collapse:collapse}td,th{padding:12px;border-bottom:1px solid #d8dfce;text-align:left}aside{background:#f0e8d2;padding:18px;line-height:1.8}a{color:#245c49}</style><h1>后与车 · 固定预算配对实验</h1><aside>基础 MCTS 自对弈；不预设后的子力价格。每种摆法各16对换色局，分别使用1,024及4,096状态访问预算。以下结果仅为弱引擎实验线索，不能证明普遍子力等价。区间基于整对对局；不同摆法和预算分别报告。<br><strong>少子 ending-2 摆法存在 Qe2–e8 一步将死，须视为特定战术局面。</strong></aside><table><tr><th>摆法</th><th>节点/步</th><th>完成</th><th>胜 / 和 / 负</th><th>纯胜率</th><th>得分率</th><th>95%区间</th></tr>${entries.map(e=>`<tr><td><a href="${e.preset}-${e.nodes}/report.html">${e.preset}</a></td><td>${e.nodes}</td><td>${e.games}/${e.scheduledGames}</td><td>${e.wins??'—'} / ${e.draws??'—'} / ${e.losses??'—'}</td><td>${pct(e.winRate)}</td><td>${pct(e.scoreRate)}</td><td>${e.score95?e.score95.map(pct).join(' — '):'待完整配对'}</td></tr>`).join('')}</table><p>未完成组的得分界限、先后手、颜色分项及每步预算请进入各组报告查看。</p>`);
}
async function worker(){while(cursor<jobs.length){const job=jobs[cursor++];console.log(`START ${job.preset} ${job.nodes}`);await mkdir(job.out,{recursive:true});
  for(let attempt=0;;attempt++){try{await new Promise((resolveJob,reject)=>{const child=spawn(process.execPath,[engine,'batch','--mode','custom','--preset',job.preset,'--nodes',String(job.nodes),'--pairs','16','--rollout','8','--out',job.out],{windowsHide:true,stdio:['ignore','pipe','pipe']});let log='';
    child.stdout.on('data',chunk=>{const line=chunk.toString();log+=line;process.stdout.write(`[${job.preset}/${job.nodes}] ${line}`);});child.stderr.on('data',chunk=>{log+=chunk.toString();process.stderr.write(chunk);});
    child.on('error',reject);child.on('exit',async code=>{await writeFile(join(job.out,'run.log'),log);code===0?resolveJob():reject(Object.assign(new Error(`${job.preset}/${job.nodes} exited ${code}`),{transient:/EPERM|EACCES|EBUSY/.test(log)}));});
  });break;}catch(e){if(!e.transient||attempt>=3)throw e;console.log(`RETRY unchanged game IDs after Windows file lock: ${job.preset}/${job.nodes}`);await new Promise(resolve=>setTimeout(resolve,500));}}}}
try{await overview();await Promise.all(Array.from({length:concurrency},worker));await overview();console.log(`COMPLETE ${root}`);}finally{await unlink(lockPath);}
