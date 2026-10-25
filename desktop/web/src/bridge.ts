export interface DocumentInfo { path: string; name: string; total: number; page: number; image: string }
import type { ReaderPage } from './source_pages.js';
export interface Snapshot { document?:{pages:ReaderPage[];metrics:{tokens?:number;tokens_per_second?:number;paused?:boolean;decode_seconds?:number;monitor?:Record<string,number|null>}}; active: boolean; metadata: {status: string; completed_pages: number[]; selected_pages: number[]; percent: number; current_page?: number; mode?: string; resumed?: boolean}; text: string; seconds: number; output: string | null; closing: boolean }
declare global { interface Window { __TAURI__?: {core: {invoke: <T>(name: string, args?: Record<string, unknown>) => Promise<T>}; event: {listen: <T>(name: string, handler: (event: {payload:T}) => void) => Promise<() => void>}} } }
export const invoke = async <T>(name: string, args?: Record<string, unknown>): Promise<T> => {
  if (!window.__TAURI__) throw new Error('Open the installed desktop app to use local files.');
  return window.__TAURI__.core.invoke<T>(name, args);
};
