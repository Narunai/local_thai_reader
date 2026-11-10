import { defaults, emptySnapshot, isSupportedNovelHost, nextChapterUrl, hashValue, speechSettings, type Chapter, type Settings, type Snapshot } from './types';
import { extractFromPage, highlightParagraph } from './extractor';
import { request } from './api';
import { sourceTab } from './reader-launch';

let creating: Promise<void> | undefined;
let visited: string[] = [];
let lastHighlight = '';
let pendingNext: {tabId: number; url: string; timer: ReturnType<typeof setTimeout>} | null = null;
let storageChain = Promise.resolve();
let controlVersion = 0;

async function settings(): Promise<Settings> {
  const data = await chrome.storage.local.get('settings');
  return {...defaults, ...data.settings};
}
function withTimeout<T>(promise: Promise<T>, ms: number, message = 'หมดเวลารอการตอบกลับ'): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), ms);
    promise.then(v => { clearTimeout(timer); resolve(v); }, e => { clearTimeout(timer); reject(e); });
  });
}
async function ensureOffscreen() {
  if (creating) return creating;
  creating = (async () => {
    const contexts = await chrome.runtime.getContexts({contextTypes: [chrome.runtime.ContextType.OFFSCREEN_DOCUMENT]});
    if (!contexts.length) {
      // WAV responses require Blob URLs. BLOBS also covers the period while
      // a cold local model is loading (which can exceed the audio-only timeout).
      // The player explicitly releases the document after 30 seconds idle.
      const bg = chrome.runtime.getManifest?.()?.background;
      const offscreenUrl = bg && 'service_worker' in bg && bg.service_worker.startsWith('dist/') ? 'dist/offscreen.html' : 'offscreen.html';
      await chrome.offscreen.createDocument({url: offscreenUrl, reasons: [chrome.offscreen.Reason.AUDIO_PLAYBACK, chrome.offscreen.Reason.BLOBS], justification: 'สร้าง Blob URL จาก WAV ของโมเดลในเครื่องและเล่นเสียงนิยายต่อเนื่อง'});
      const data = await chrome.storage.local.get('snapshot');
      const saved: Snapshot = data.snapshot ?? emptySnapshot(await settings());
      if (saved.chapter) {
        // Chrome tab IDs are not stable across browser sessions.
        const tabs = await chrome.tabs.query({});
        const source = tabs.find(t => t.id === saved.chapter?.tabId && t.url === saved.chapter?.url)
          ?? tabs.find(t => t.url === saved.chapter?.url);
        saved.chapter.tabId = source?.id;
        if (source?.id && source.status === 'complete' && !source.discarded && !saved.chapter.selection) {
          const fresh = await withTimeout(extract(source.id, false, 1), 1500).catch(() => null);
          if (fresh && fresh.contentHash !== saved.chapter.contentHash) saved.chapter.tabId = undefined;
        }
      }
      await withTimeout(chrome.runtime.sendMessage({target: 'player', type: 'RESTORE', snapshot: saved, settings: await settings()}), 5000).catch(() => {});
    }
  })().finally(() => {creating = undefined;});
  return creating;
}
async function player(message: object) {
  await ensureOffscreen();
  const response = await withTimeout<any>(chrome.runtime.sendMessage({...message, target: 'player'}), 10000, 'เครื่องเล่นเสียงไม่ตอบกลับ');
  if (!response?.ok) throw new Error(response?.error || 'เครื่องเล่นเสียงไม่ตอบกลับ');
  return response.value;
}
async function extract(tabId: number, selection = false, maxAttempts = 20): Promise<Chapter> {
  let results;
  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    try {
      results = await withTimeout(chrome.scripting.executeScript({target: {tabId}, func: extractFromPage, args: [selection]}), 3000, 'หน้าเว็บไม่ตอบกลับ');
      if (results[0]?.result) break;
    } catch (error) {
      const text = (error as Error).message;
      if (/cannot access|permission|extensions gallery|chrome:\/\//i.test(text)) throw new Error('เข้าถึงหน้านี้ไม่ได้ · สำหรับเว็บอื่น ให้คลิกไอคอน Extension บนแท็บนั้นหนึ่งครั้ง แล้วเลือกข้อความใหม่');
      if (selection || attempt === maxAttempts - 1 || !/ไม่พบเนื้อหานิยาย|เนื้อหาว่าง/.test(text)) throw error;
    }
    await new Promise(r => setTimeout(r, 250));
  }
  const chapter = results?.[0]?.result;
  if (!chapter) throw new Error('อ่านหน้าเว็บไม่ได้ กรุณารีเฟรชแล้วลองใหม่');
  chapter.tabId = tabId;
  chapter.contentHash = await hashValue(chapter.paragraphs);
  return chapter;
}
async function clearHighlight(snapshot?: Snapshot) {
  const data = snapshot ?? (await chrome.storage.local.get('snapshot')).snapshot;
  if (data?.chapter?.tabId) {
    await chrome.scripting.executeScript({target: {tabId: data.chapter.tabId}, func: highlightParagraph, args: [-1, false, data.chapter.url]}).catch(() => {});
  }
  lastHighlight = '';
}
async function attachSourceForResume() {
  const version = controlVersion;
  const snapshot: Snapshot = await player({type:'GET_STATE'});
  const chapter = snapshot.chapter;
  if (!chapter || chapter.selection || !isSupportedNovelHost(new URL(chapter.url).hostname)) return;
  const tabs = await chrome.tabs.query({});
  if(version!==controlVersion) return;
  let source = tabs.find(t => t.id === chapter.tabId && t.url === chapter.url)
    ?? tabs.find(t => t.url === chapter.url);
  if (!source) source = await chrome.tabs.create({url:chapter.url, active:false});
  if (!source.id) return;
  const tabId = source.id;
  await player({type:'SOURCE_TAB',tabId,url:chapter.url});
  if (source.status !== 'complete') {
    await new Promise<void>((resolve,reject) => {
      const timer = setTimeout(() => {chrome.tabs.onUpdated.removeListener(updated); reject(new Error('โหลดหน้านิยายเดิมไม่สำเร็จ'));},25000);
      const updated = (id:number, info:chrome.tabs.TabChangeInfo) => {
        if(id===tabId && info.status==='complete') {clearTimeout(timer);chrome.tabs.onUpdated.removeListener(updated);resolve();}
      };
      chrome.tabs.onUpdated.addListener(updated);
      void chrome.tabs.get(tabId).then(t => {if(t.status==='complete')updated(tabId,{status:'complete'});}).catch(() => {
        clearTimeout(timer);chrome.tabs.onUpdated.removeListener(updated);reject(new Error('แท็บนิยายถูกปิด'));
      });
    });
  }
  const fresh = await extract(tabId).catch(() => null);
  if(version!==controlVersion) return;
  lastHighlight = '';
  if (fresh && fresh.contentHash === chapter.contentHash) await player({type:'SOURCE_TAB',tabId,url:chapter.url});
  else await player({type:'SOURCE_TAB',tabId:undefined,url:chapter.url});
}
let navigationEpoch = 0;
function clearNext() { if (pendingNext) clearTimeout(pendingNext.timer); pendingNext = null; navigationEpoch++; }

chrome.tabs.onUpdated.addListener((tabId, info, tab) => {
  if (info.status !== 'complete' || !pendingNext || tabId !== pendingNext.tabId || tab.url !== pendingNext.url) return;
  clearNext();
  const generation = navigationEpoch;
  void extract(tabId).then(chapter => generation === navigationEpoch ? player({type: 'LOAD', chapter, settings: undefined}) : undefined).catch(error => player({type: 'ERROR', error: error.message}));
});
chrome.tabs.onRemoved.addListener(tabId => {
  if (pendingNext?.tabId === tabId) { clearNext(); void player({type: 'ERROR', error: 'แท็บนิยายถูกปิด'}); }
});

async function handle(message: any, sender: chrome.runtime.MessageSender): Promise<any> {
  if (message.target !== 'worker' || sender.id !== chrome.runtime.id || !sender.url?.startsWith(chrome.runtime.getURL(''))) return;
  switch (message.type) {
    case 'SETTINGS_GET': return settings();
    case 'SETTINGS_SAVE': {
      controlVersion++;
      const value: Settings = {...defaults, ...message.settings};
      value.geminiBatches = value.geminiBatches === 3 ? 3 : 4;
      const previous = await settings();
      if (!value.autoNext || JSON.stringify(speechSettings(value)) !== JSON.stringify(speechSettings(previous))) clearNext();
      value.rate = Math.max(.75, Math.min(1.5, Number(value.rate) || 1));
      value.volume = Math.max(0, Math.min(1, Number(value.volume) ?? 1));
      value.bgmVolume = Math.max(0, Math.min(1, Number(value.bgmVolume) ?? 0.2));
      value.bgmEnabled = value.bgmEnabled !== false;
      await chrome.storage.local.set({settings: value});
      return player({type: 'SETTINGS', settings: value}).catch(() => value);
    }
    case 'HEALTH': {
      const config = await settings();
      return {health: await request(config.token, '/health'), voices: await request(config.token, '/voices')};
    }
    case 'GEMINI_STATUS': return request((await settings()).token, '/gemini');
    case 'GEMINI_KEY_SAVE': return request((await settings()).token, '/gemini', {method:'POST', body:JSON.stringify({api_key:message.apiKey})});
    case 'GEMINI_KEY_DELETE': return request((await settings()).token, '/gemini', {method:'DELETE'});
    case 'GEMINI_TEST': return request((await settings()).token, '/gemini/test', {method:'POST', body:JSON.stringify({model:message.model})}, 35000);
    case 'GET_STATE': return player({type: 'GET_STATE'});
    case 'LOAD': {
      controlVersion++;
      clearNext();
      await clearHighlight();
      const tab = await sourceTab(sender);
      if (!tab.id) throw new Error('ไม่พบแท็บที่เปิดอยู่');
      const chapter = await extract(tab.id, message.selection);
      visited = [chapter.url];
      await chrome.storage.session.set({visited});
      const saved = (await chrome.storage.local.get('positions')).positions?.[chapter.url];
      return player({type: 'LOAD', chapter, settings: await settings(), resume: saved});
    }
    case 'CONTROL':
      controlVersion++;
      if (['stop', 'seek', 'previous', 'next', 'clear'].includes(message.action)) clearNext();
      if (message.action === 'clear') {
        const previous: Snapshot | undefined = (await chrome.storage.local.get('snapshot')).snapshot;
        await clearHighlight(previous);
        visited = [];
        await chrome.storage.session.set({visited});
        if (previous?.chapter?.url) {
          const data = await chrome.storage.local.get('positions');
          if (data.positions?.[previous.chapter.url]) {
            delete data.positions[previous.chapter.url];
            await chrome.storage.local.set({positions: data.positions});
          }
        }
      }
      if (message.action === 'play') {
        const tab = await sourceTab(sender);
        const live: Snapshot = await player({type: 'GET_STATE'});
        const activeHost = tab?.url ? (() => { try { return new URL(tab.url).hostname; } catch { return ''; } })() : '';
        if (tab?.id && tab.url && isSupportedNovelHost(activeHost) && live.chapter?.url !== tab.url) {
          clearNext();
          await clearHighlight(live);
          const chapter = await extract(tab.id, false);
          visited = [chapter.url];
          await chrome.storage.session.set({visited});
          const saved = (await chrome.storage.local.get('positions')).positions?.[chapter.url];
          return player({type: 'LOAD', chapter, settings: await settings(), resume: saved});
        }
        void attachSourceForResume().catch(() => {});
      }
      return player(message);
    case 'CLOSE_IDLE': {
      const version = controlVersion;
      const live: Snapshot = await player({type: 'GET_STATE'});
      if (['playing', 'buffering'].includes(live.status)) return {ok:true};
      await storageChain;
      if (version === controlVersion) await chrome.offscreen.closeDocument();
      return {ok:true};
    }
    case 'STATE': {
      const snapshot: Snapshot = message.snapshot;
      // Queue writes so a slow checkpoint cannot overwrite a newer stop/seek.
      storageChain = storageChain.then(async () => {
        const data = await chrome.storage.local.get('positions');
        const positions = data.positions ?? {};
        if (snapshot.chapter) positions[snapshot.chapter.url] = {
          index: snapshot.index, offset: snapshot.offset, contentHash: snapshot.chapter.contentHash,
          speechHash: await hashValue(speechSettings(snapshot.settings)), savedAt: Date.now()
        };
        const entries = Object.entries<any>(positions).sort((a,b) => b[1].savedAt-a[1].savedAt).slice(0, 30);
        await chrome.storage.local.set({snapshot, positions: Object.fromEntries(entries)});
      }).catch(() => {});
      const chunk = snapshot.chunks[snapshot.index];
      const key = snapshot.status === 'stopped' || snapshot.status === 'ended' || snapshot.status === 'error' ? '' : `${snapshot.chapter?.url}:${chunk?.paragraph}`;
      if (snapshot.chapter?.tabId && chunk && key !== lastHighlight) {
        lastHighlight = key;
        await chrome.scripting.executeScript({target: {tabId: snapshot.chapter.tabId}, func: highlightParagraph,
          args: [key ? chunk.paragraph : -1, snapshot.settings.autoScroll && !!key, snapshot.chapter.url]}).catch(() => {});
      }
      void chrome.runtime.sendMessage({target: 'panel', type: 'STATE', snapshot}).catch(() => {});
      return {ok: true};
    }
    case 'CHAPTER_ENDED': {
      const generation = navigationEpoch;
      const snapshot: Snapshot = message.snapshot;
      const chapter = snapshot.chapter;
      if (!chapter?.nextUrl || !snapshot.settings.autoNext) return {ok: true};
      const live: Snapshot = await player({type: 'GET_STATE'});
      if (generation !== navigationEpoch || live.status !== 'ended' || live.chapter?.url !== chapter.url) return {ok: true};
      visited = (await chrome.storage.session.get('visited')).visited ?? visited;
      const next = nextChapterUrl(chapter.url, chapter.nextUrl, visited);
      if (!next || !chapter.tabId) throw new Error('หยุดต่อบท: ลิงก์ถัดไปไม่ถูกต้องหรือเคยอ่านแล้ว');
      visited.push(next);
      await chrome.storage.session.set({visited});
      if (generation !== navigationEpoch) return {ok: true};
      const timer = setTimeout(() => {
        pendingNext = null;
        void player({type: 'ERROR', error: 'โหลดตอนถัดไปไม่สำเร็จ กรุณาเปิดหน้าเว็บแล้วเริ่มใหม่'});
      }, 25000);
      pendingNext = {tabId: chapter.tabId, url: next, timer};
      await chrome.tabs.update(chapter.tabId, {url: next});
      return {ok: true};
    }
  }
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message.target !== 'worker') return;
  handle(message, sender).then(value => respond({ok: true, value})).catch(error => respond({ok: false, error: error.message}));
  return true;
});
