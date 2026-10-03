import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
import { spawn } from 'node:child_process';
const root=resolve('dist/renderer');
const port=Number(process.env.XQLAB_PORT??4178);
const url=`http://127.0.0.1:${port}/#lab`;
const openBrowser=()=>{const child=spawn('powershell.exe',['-NoProfile','-Command',`Start-Process '${url}'`],{windowsHide:true,stdio:'ignore'});child.unref();};
const types={'.html':'text/html; charset=utf-8','.js':'text/javascript','.mjs':'text/javascript','.css':'text/css','.wasm':'application/wasm','.svg':'image/svg+xml','.json':'application/json','.onnx':'application/octet-stream'};
await stat(resolve(root,'index.html')).catch(()=>{throw new Error('请先执行 npm.cmd run lab:build');});
const server=createServer(async(req,res)=>{
  try{const url=new URL(req.url,'http://127.0.0.1');const path=resolve(root,'.'+decodeURIComponent(url.pathname==='/'?'/index.html':url.pathname));if(!path.startsWith(root+sep))throw new Error('无效路径');
    const bytes=await readFile(path);res.writeHead(200,{'Content-Type':types[extname(path)]??'application/octet-stream','Cache-Control':'no-cache','X-Xiangqi-Lab':'1'});res.end(bytes);
  }catch{res.writeHead(404);res.end('Not found');}
});
server.on('error',async error=>{
  if(error.code==='EADDRINUSE')try{const response=await fetch(url,{signal:AbortSignal.timeout(2000)});if(response.headers.get('X-Xiangqi-Lab')==='1'){console.log(`已有本地服务：${url}`);if(process.argv.includes('--open'))openBrowser();return;}}catch{}
  console.error(error);process.exitCode=1;
});
server.listen(port,'127.0.0.1',()=>{console.log(`四模式本地网页 ${url}\n关闭此终端停止本地服务。`);if(process.argv.includes('--open'))openBrowser();});
