import { contextBridge, ipcRenderer } from 'electron';
import type { SavedGameV1, XiangqiBridge } from '../shared/protocol.js' with { "resolution-mode": "import" };

const bridge: XiangqiBridge = {
  request: <T,>(method: string, params: Record<string, unknown> = {}) => ipcRenderer.invoke('engine:request', method, params) as Promise<T>,
  saveGame: (game: SavedGameV1) => ipcRenderer.invoke('file:saveGame', game),
  openGame: () => ipcRenderer.invoke('file:openGame'),
};
contextBridge.exposeInMainWorld('xiangqi', bridge);
