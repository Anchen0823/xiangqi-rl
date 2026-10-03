import type { XiangqiBridge } from '../shared/protocol';
import type { DesktopModelsBridge } from '../shared/desktop-models';

declare global { interface Window { xiangqi: XiangqiBridge; desktopModels?: DesktopModelsBridge } }
export {};

