import { app, BrowserWindow, dialog, ipcMain } from 'electron';
import { ChildProcessWithoutNullStreams, spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { readFile, writeFile } from 'node:fs/promises';
import { join, resolve, sep } from 'node:path';
import { randomUUID, createHash } from 'node:crypto';
import type { DesktopModel } from '../shared/desktop-models.js' with { "resolution-mode": "import" };
import type { EngineResponse, SavedGameV1 } from '../shared/protocol.js' with { "resolution-mode": "import" };

let mainWindow: BrowserWindow | null = null;
let engine: ChildProcessWithoutNullStreams | null = null;
let engineBuffer = '';
const pending = new Map<string, { resolve: (value: unknown) => void; reject: (reason: Error) => void }>();
type InstalledModel = DesktopModel & {file?:string;manifest?:string};
let installedModels: InstalledModel[]=[];
const assetsRoot=()=>app.isPackaged?process.resourcesPath:join(app.getAppPath(),'build','desktop-assets');
function modelFile(file:string):string{
  const root=join(assetsRoot(),'models'),path=resolve(root,file);
  if(!path.startsWith(root+sep))throw new Error('Invalid model path');
  return path;
}
async function setupModels():Promise<void>{
  try{installedModels=JSON.parse(await readFile(join(assetsRoot(),'models','catalog.json'),'utf8')).models;}
  catch{installedModels=['standard','custom','jieqi','banqi'].map(mode=>({mode,name:'模型空位 · 尚未训练',note:'使用基础搜索',kind:mode==='standard'?'nnue':'onnx',status:'empty'} as InstalledModel));}
  for(const model of installedModels){
    if(model.status!=='available')continue;
    try{const bytes=await readFile(modelFile(model.file!));if(createHash('sha256').update(bytes).digest('hex')!==model.sha256)throw new Error('权重校验失败');}
    catch{model.status='error';model.note='模型缺失或校验失败，使用基础搜索';}
  }
  const standard=installedModels.find(m=>m.mode==='standard'&&m.status==='available');
  // Explicit development overrides retain the existing candidate/night-training workflow.
  if(standard&&(app.isPackaged||!process.env.XIANGQI_NNUE_PATH)){
    process.env.XIANGQI_NNUE_PATH=modelFile(standard.file!);
    process.env.XIANGQI_PIKAFISH_PATH=join(assetsRoot(),'native','pikafish.exe');
    process.env.XIANGQI_EMBEDDED_NNUE='0';process.env.XIANGQI_SEARCH_BACKEND='pikafish';
    delete process.env.XIANGQI_UCI_VARIANT;
  }else if(app.isPackaged){
    delete process.env.XIANGQI_NNUE_PATH;delete process.env.XIANGQI_PIKAFISH_PATH;
    delete process.env.XIANGQI_EMBEDDED_NNUE;delete process.env.XIANGQI_SEARCH_BACKEND;
  }
}
ipcMain.handle('models:list',()=>installedModels.map(({file,manifest,...model})=>model));
ipcMain.handle('models:load',async(_event,mode:string,hash:string)=>{
  const model=installedModels.find(m=>m.mode===mode&&m.rulesHash===hash&&m.status==='available'&&m.kind==='onnx');
  if(!model)return null;
  const bytes=await readFile(modelFile(model.file!));
  if(createHash('sha256').update(bytes).digest('hex')!==model.sha256)throw new Error('模型文件 SHA256 不匹配');
  const manifest=JSON.parse(await readFile(modelFile(model.manifest!),'utf8'));
  return {model,manifest,bytes:new Uint8Array(bytes)};
});

function enginePath(): string {
  const bundled = join(process.resourcesPath, 'native', 'xiangqi-engine.exe');
  const development = join(app.getAppPath(), 'build', 'native', 'xiangqi-engine.exe');
  return app.isPackaged ? bundled : development;
}

function rejectPending(message: string): void {
  for (const request of pending.values()) request.reject(new Error(message));
  pending.clear();
}

function startEngine(): void {
  if (engine && !engine.killed) return;
  const executable = enginePath();
  if (!existsSync(executable)) throw new Error(`Native engine not found: ${executable}. Run npm run native:build.`);
  engine = spawn(executable, [], { stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true, cwd:app.isPackaged?process.resourcesPath:app.getAppPath() });
  engineBuffer = '';
  engine.stdout.setEncoding('utf8');
  engine.stdout.on('data', (chunk: string) => {
    engineBuffer += chunk;
    let newline = engineBuffer.indexOf('\n');
    while (newline >= 0) {
      const line = engineBuffer.slice(0, newline).trim();
      engineBuffer = engineBuffer.slice(newline + 1);
      if (line) {
        try {
          const response = JSON.parse(line) as EngineResponse;
          const request = pending.get(response.id);
          if (request) {
            pending.delete(response.id);
            response.ok ? request.resolve(response.data) : request.reject(new Error(response.error ?? 'Native engine error'));
          }
        } catch (error) {
          console.error('Invalid engine response', line, error);
        }
      }
      newline = engineBuffer.indexOf('\n');
    }
  });
  engine.stderr.setEncoding('utf8');
  engine.stderr.on('data', (chunk: string) => console.error(`[native] ${chunk.trimEnd()}`));
  engine.on('exit', (code) => {
    engine = null;
    rejectPending(`Native engine exited with code ${code ?? 'unknown'}`);
  });
}

function engineRequest(method: string, params: Record<string, unknown> = {}): Promise<unknown> {
  startEngine();
  const id = randomUUID();
  return new Promise((resolve, reject) => {
    pending.set(id, { resolve, reject });
    engine?.stdin.write(`${JSON.stringify({ id, method, params })}\n`, (error) => {
      if (error) { pending.delete(id); reject(error); }
    });
  });
}

async function createWindow(): Promise<void> {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 900,
    minWidth: 1050,
    minHeight: 720,
    backgroundColor: '#17120d',
    title: '弈境 · Xiangqi RL',
    webPreferences: {
      preload: join(__dirname, '..', 'preload', 'index.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  });
  mainWindow.setMenuBarVisibility(false);
  const devUrl = app.isPackaged?undefined:process.env.VITE_DEV_SERVER_URL;
  const requestedMode=process.env.XQLAB_MODE;
  const hash=requestedMode&&['standard','lab','jieqi','banqi'].includes(requestedMode)?requestedMode:undefined;
  if (devUrl) {const url=new URL(devUrl);if(hash)url.hash=hash;await mainWindow.loadURL(url.href);}
  else await mainWindow.loadFile(join(app.getAppPath(), 'dist', 'renderer', 'index.html'),{hash});
}

ipcMain.handle('engine:request', (_event, method: string, params?: Record<string, unknown>) => engineRequest(method, params));
ipcMain.handle('file:saveGame', async (_event, game: SavedGameV1) => {
  const result = await dialog.showSaveDialog(mainWindow!, {
    title: '保存棋局',
    defaultPath: `xiangqi-${new Date().toISOString().slice(0, 10)}.xqgame`,
    filters: [{ name: 'Xiangqi game', extensions: ['xqgame'] }],
  });
  if (result.canceled || !result.filePath) return { canceled: true };
  await writeFile(result.filePath, `${JSON.stringify(game, null, 2)}\n`, 'utf8');
  return { canceled: false, path: result.filePath };
});
ipcMain.handle('file:openGame', async () => {
  const result = await dialog.showOpenDialog(mainWindow!, {
    title: '载入棋局', properties: ['openFile'], filters: [{ name: 'Xiangqi game', extensions: ['xqgame'] }],
  });
  if (result.canceled || !result.filePaths[0]) return { canceled: true };
  const game = JSON.parse(await readFile(result.filePaths[0], 'utf8')) as SavedGameV1;
  if (game.schemaVersion !== 1 || !Array.isArray(game.moves)) throw new Error('Unsupported or damaged game file');
  return { canceled: false, game };
});

app.setName('弈境');
app.whenReady().then(async () => { await setupModels();startEngine(); await createWindow(); }).catch(error=>{dialog.showErrorBox('弈境启动失败',String(error));app.quit();});
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) void createWindow(); });
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('before-quit', () => { if (engine && !engine.killed) engine.kill(); });
