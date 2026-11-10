export interface Chapter { title: string; url: string; paragraphs: string[]; nextUrl: string | null; tabId?: number; selection?: boolean; contentHash?: string }
export interface Settings { token: string; voice: string; rate: number; volume: number; bgmEnabled: boolean; bgmVolume: number; autoNext: boolean; autoScroll: boolean; dictionary: Record<string, string>; geminiEnabled: boolean; geminiModel: string; geminiRevision: string; geminiBatches: number }
export interface BgmCue { track: string; tempo: string; rate: number; label: string }
export interface Chunk { index: number; paragraph: number; text: string; ready: boolean; seconds: number; bgm?: BgmCue }
export interface PronunciationProgress { total_batches: number; ready_batches: number }
export interface Job { id: string; state: string; error?: string; chunks: Chunk[]; pronunciation?: PronunciationProgress }
export interface Voice { id: string; name: string; ready: boolean; reason: string; device: string }
export interface Snapshot { chapter: Chapter | null; chunks: Chunk[]; index: number; offset: number; status: string; error: string; settings: Settings; jobId?: string; pronunciation?: PronunciationProgress }
export const defaults: Settings = { token: '', voice: 'omnivoice:reference', rate: 1, volume: 1, bgmEnabled: true, bgmVolume: 0.2, autoNext: true, autoScroll: true, dictionary: {}, geminiEnabled: false, geminiModel: 'gemini-3.5-flash-lite', geminiRevision: '', geminiBatches: 4 };
export function speechSettings(settings: Settings): unknown[] {
  const values: unknown[] = [settings.voice, settings.dictionary];
  if (settings.geminiEnabled) values.push({model: settings.geminiModel, revision: settings.geminiRevision, batches: settings.geminiBatches || 4, version: 2});
  return values;
}
export const emptySnapshot = (settings: Settings): Snapshot => ({ chapter: null, chunks: [], index: 0, offset: 0, status: 'idle', error: '', settings });
export async function hashValue(value: unknown): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(value));
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(b => b.toString(16).padStart(2, '0')).join('');
}
const SUPPORTED_HOSTS = new Set(['og-thai.blogspot.com', 'www.nekopost.net', 'nekopost.net']);
export function isSupportedNovelHost(hostname: string): boolean {
  return SUPPORTED_HOSTS.has(hostname);
}
export function nextChapterUrl(current: string, candidate: string | null, visited: string[]): string | null {
  if (!candidate) return null;
  const url = new URL(candidate, current);
  const old = new URL(current);
  url.hash = ''; old.hash = '';
  if (url.protocol !== 'https:' || !isSupportedNovelHost(url.hostname) || url.origin !== old.origin || url.href === old.href || visited.includes(url.href)) return null;
  return url.href;
}
