export type DesktopMode = 'standard' | 'custom' | 'jieqi' | 'banqi';
export interface DesktopModel {
  mode: DesktopMode;
  name: string;
  note: string;
  kind: 'nnue' | 'onnx';
  status: 'available' | 'empty' | 'error';
  rulesHash?: string;
  sha256?: string;
}
export interface DesktopModelsBridge {
  list(): Promise<DesktopModel[]>;
  load(mode: DesktopMode, rulesHash: string): Promise<{model: DesktopModel; manifest: unknown; bytes: Uint8Array} | null>;
}
