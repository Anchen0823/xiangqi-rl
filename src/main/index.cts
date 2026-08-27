import { app, BrowserWindow, dialog, ipcMain } from 'electron';
import { ChildProcessWithoutNullStreams, spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import type { EngineResponse, SavedGameV1 } from '../shared/protocol.js' with { "resolution-mode": "import" };

let mainWindow: BrowserWindow | null = null;
let engine: ChildProcessWithoutNullStreams | null = null;
let engineBuffer = '';
const pending = new Map<string, { resolve: (value: unknown) => void; reject: (reason: Error) => void }>();

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
  engine = spawn(executable, [], { stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true });
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
  const devUrl = process.env.VITE_DEV_SERVER_URL;
  if (devUrl) await mainWindow.loadURL(devUrl);
  else await mainWindow.loadFile(join(app.getAppPath(), 'dist', 'renderer', 'index.html'));
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

app.whenReady().then(async () => { startEngine(); await createWindow(); });
app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) void createWindow(); });
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
app.on('before-quit', () => { if (engine && !engine.killed) engine.kill(); });
