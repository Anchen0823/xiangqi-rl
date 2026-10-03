import { cp, mkdir, readFile, writeFile, rename, access } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
const root=resolve('.'), version=JSON.parse(await readFile('package.json','utf8')).version;
const tag=new Date().toISOString().replace(/[-:]/g,'').replace(/\..*/,'').replace('T','-');
const out=join(root,'dist','desktop',`XiangqiLab-${version}-win-x64-${tag}`);
await mkdir(out,{recursive:true});
// Copy the installed, pinned Electron runtime. This app has no main-process npm runtime dependencies.
await cp(join(root,'node_modules/electron/dist'),out,{recursive:true,filter:path=>!path.endsWith('default_app.asar')});
await rename(join(out,'electron.exe'),join(out,'弈境.exe'));
const app=join(out,'resources/app');await mkdir(app,{recursive:true});
for(const folder of ['dist/renderer','dist-electron'])await cp(join(root,folder),join(app,folder),{recursive:true});
await writeFile(join(app,'package.json'),JSON.stringify({name:'xiangqi-lab',version,main:'dist-electron/main/index.cjs',type:'module'},null,2));
const catalog=JSON.parse(await readFile(join(root,'build/desktop-assets/models/catalog.json'),'utf8'));
await mkdir(join(out,'resources/models'),{recursive:true});
await writeFile(join(out,'resources/models/catalog.json'),JSON.stringify(catalog,null,2));
for(const model of catalog.models.filter(m=>m.status==='available')){
  await mkdir(join(out,'resources/models',model.mode),{recursive:true});
  await cp(join(root,'build/desktop-assets/models',model.file),join(out,'resources/models',model.file));
  if(model.manifest)await cp(join(root,'build/desktop-assets/models',model.manifest),join(out,'resources/models',model.manifest));
}
await mkdir(join(out,'resources/native'),{recursive:true});
await cp(join(root,'build/native/xiangqi-engine.exe'),join(out,'resources/native/xiangqi-engine.exe'));
if(catalog.models.some(m=>m.mode==='standard'&&m.status==='available'))await cp(join(root,'build/desktop-assets/native/pikafish.exe'),join(out,'resources/native/pikafish.exe'));
for(const file of ['LICENSE','THIRD_PARTY_NOTICES.md','desktop-models.json','package-lock.json'])await cp(join(root,file),join(app,file));
await cp(join(root,'third_party'),join(app,'third_party'),{recursive:true});
// Ship the corresponding local application sources alongside a rebuild guide.
for(const folder of ['src','native/src','native/include','native/tests','scripts/desktop'])await cp(join(root,folder),join(out,'source',folder),{recursive:true});
await mkdir(join(out,'source/docs'),{recursive:true});
await cp(join(root,'docs/desktop-app.md'),join(out,'source/docs/desktop-app.md'));
await cp(join(root,'third_party'),join(out,'source/third_party'),{recursive:true});
for(const file of ['LICENSE','THIRD_PARTY_NOTICES.md'])await cp(join(root,file),join(out,'source',file));
for(const file of ['package.json','package-lock.json','native/CMakeLists.txt','vite.config.ts','tsconfig.json','tsconfig.app.json','tsconfig.electron.json','scripts/native.ps1'])await cp(join(root,file),join(out,'source',file));
await cp(join(root,'scripts/variants'),join(out,'source/scripts/variants'),{recursive:true});
await cp(join(root,'desktop-models.json'),join(out,'source/desktop-models.json'));
await cp(join(root,'docs/desktop-app.md'),join(out,'使用说明.md'));
const manifest={version,platform:'win32-x64',builtAt:new Date().toISOString(),models:catalog.models,
  executable:'弈境.exe',electron:JSON.parse(await readFile('node_modules/electron/package.json','utf8')).version};
await writeFile(join(out,'package-manifest.json'),JSON.stringify(manifest,null,2));
await writeFile(join(root,'dist/desktop/latest.json'),JSON.stringify({directory:out,executable:join(out,'弈境.exe')},null,2));
console.log(`Desktop application: ${join(out,'弈境.exe')}`);
