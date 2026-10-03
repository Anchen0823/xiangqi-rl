import { readFile, writeFile, mkdir, copyFile } from 'node:fs/promises';
import { resolve, join, dirname } from 'node:path';
import { createHash } from 'node:crypto';
const root=resolve('.'), out=join(root,'build/desktop-assets/models');
await mkdir(out,{recursive:true});
const source=JSON.parse(await readFile('desktop-models.json','utf8'));
const models=[];
for(const item of source.models){
  if(!['standard','jieqi','custom','banqi'].includes(item.mode))throw new Error('Invalid model mode');
  if(!item.source){models.push({...item,status:'empty'});continue;}
  let bytes;
  try{bytes=await readFile(resolve(root,item.source));}catch(e){if(e.code!=='ENOENT')throw e;models.push({mode:item.mode,name:'模型空位 · 尚未训练',kind:item.kind,status:'empty',note:'未提供可用权重，使用基础搜索'});continue;}
  const sha256=createHash('sha256').update(bytes).digest('hex');
  const folder=join(out,item.mode);await mkdir(folder,{recursive:true});
  let manifest;
  if(item.kind==='onnx'){
    manifest=JSON.parse(await readFile(resolve(root,item.source.replace(/\.onnx$/,'.json')),'utf8'));
    if(manifest.sha256!==sha256||manifest.training?.mode!==item.mode)throw new Error(`${item.mode}: incompatible model manifest`);
    await writeFile(join(folder,'candidate.json'),JSON.stringify(manifest,null,2));
  }
  await writeFile(join(folder,`candidate.${item.kind}`),bytes);
  if(item.engine){await mkdir(join(root,'build/desktop-assets/native'),{recursive:true});await copyFile(resolve(root,item.engine),join(root,'build/desktop-assets/native/pikafish.exe'));}
  models.push({mode:item.mode,name:item.name,note:item.note,kind:item.kind,status:'available',sha256,
    file:`${item.mode}/candidate.${item.kind}`,...(manifest?{rulesHash:manifest.rulesHash,manifest:`${item.mode}/candidate.json`}:{}),source:item.source});
}
await writeFile(join(out,'catalog.json'),JSON.stringify({schemaVersion:1,models},null,2));
console.log(models.map(m=>`${m.mode}: ${m.status} ${m.name}`).join('\n'));
