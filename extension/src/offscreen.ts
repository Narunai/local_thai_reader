import { emptySnapshot, defaults, hashValue, speechSettings, type Settings, type Snapshot, type Chapter, type Job } from './types';
import { request, audioBlob } from './api';

let state = emptySnapshot(defaults);
const bgmAudio = new Audio();
bgmAudio.loop = true;
bgmAudio.preservesPitch = true;
const audio = new Audio();
audio.preservesPitch = true;
let currentBgmTrack = '';
const bgmCache = new Map<string, string>();
let epoch = 0;
let controller = new AbortController();
let timer: ReturnType<typeof setTimeout> | undefined;
let objectUrl = '';
let checkpoint = 0;
let restoringOffset = 0;
let idleTimer: ReturnType<typeof setTimeout> | undefined;
let retries = 0;

function copy(): Snapshot { return structuredClone(state); }
function publish() {
  clearTimeout(idleTimer);
  if (!['playing','buffering'].includes(state.status)) {
    idleTimer = setTimeout(() => {
      void chrome.runtime.sendMessage({target:'worker',type:'CLOSE_IDLE'}).catch(() => {});
    }, 30000);
  }
  void chrome.runtime.sendMessage({target: 'worker', type: 'STATE', snapshot: copy()}).catch(() => {});
}
function stopBgm() {
  bgmAudio.pause();
}
async function syncBgm(generation: number) {
  const cue = state.chunks[state.index]?.bgm;
  if (generation !== epoch || state.status !== 'playing' || !state.settings.bgmEnabled || state.settings.bgmVolume <= 0 || !cue?.track) {
    stopBgm();
    return;
  }
  const track = cue.track;
  const rate = cue.rate || 0.92;
  bgmAudio.volume = Math.max(0, Math.min(1, state.settings.bgmVolume));
  bgmAudio.playbackRate = rate;
  try {
    if (currentBgmTrack !== track || !bgmAudio.getAttribute('src')) {
      let url = bgmCache.get(track);
      if (!url) {
        const blob = await audioBlob(state.settings.token, `/bgm/${track}`, controller.signal);
        if (generation !== epoch) return;
        url = URL.createObjectURL(blob);
        bgmCache.set(track, url);
      }
      currentBgmTrack = track;
      bgmAudio.src = url;
    }
    if (generation === epoch && state.status === 'playing') {
      await bgmAudio.play().catch(() => {});
    }
  } catch {
    // Non-fatal: narration continues even if background track fails to load
  }
}
function disposeAudio() {
  audio.pause(); audio.removeAttribute('src'); audio.load();
  audio.onended = null; audio.onloadedmetadata = null;
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = '';
}
function interrupt(cancelJob: boolean) {
  retries = 0;
  epoch++;
  controller.abort(); controller = new AbortController();
  clearTimeout(timer);
  audio.pause();
  stopBgm();
  if (cancelJob && state.jobId) {
    const id = state.jobId; state.jobId = undefined;
    void request(state.settings.token, `/jobs/${id}`, {method: 'DELETE'}).catch(() => {});
  }
  return epoch;
}
function fail(error: unknown) {
  if ((error as Error).name === 'AbortError') return;
  interrupt(true); disposeAudio();
  state.status = 'error'; state.error = (error as Error).message || String(error); publish();
}
function schedule(generation: number) {
  timer = setTimeout(() => {void step(generation).catch(error => stepError(error,generation));}, 400);
}
function stepError(error: any, generation: number) {
  if(generation!==epoch || error?.name==='AbortError') return;
  if(error?.transient && retries<3){
    retries++; state.status='buffering'; state.error='กำลังเชื่อมต่อระบบเสียงใหม่…'; publish();
    timer=setTimeout(()=>{void step(generation).catch(e=>stepError(e,generation));},retries*1000);
  } else fail(error);
}
async function newJob(generation: number) {
  if (!state.chapter) return;
  const job = await request<Job>(state.settings.token, '/jobs', {method: 'POST', signal: controller.signal,
    body: JSON.stringify({paragraphs: state.chapter.paragraphs, voice: state.settings.voice, dictionary: state.settings.dictionary,
      gemini: {enabled: !!state.settings.geminiEnabled, model: state.settings.geminiModel || defaults.geminiModel, batches: state.settings.geminiBatches || 4}})});
  if (generation !== epoch) return;
  state.jobId = job.id; state.chunks = job.chunks;
  state.pronunciation = job.pronunciation;
  state.index = Math.min(state.index, Math.max(0, job.chunks.length - 1));
}
async function step(generation: number): Promise<void> {
  if (generation !== epoch || !state.chapter || state.status === 'paused' || state.status === 'stopped') return;
  if (!state.jobId) await newJob(generation);
  if (generation !== epoch || !state.jobId) return;
  let job: Job;
  try {
    await request(state.settings.token, `/jobs/${state.jobId}/cursor`, {method: 'POST', signal: controller.signal, body: JSON.stringify({index: state.index})});
    job = await request<Job>(state.settings.token, `/jobs/${state.jobId}`, {signal: controller.signal});
  } catch (error) {
    if ((error as any).status === 404 || (error as any).status === 410) {
      state.jobId = undefined; await newJob(generation); schedule(generation); return;
    }
    throw error;
  }
  if (generation !== epoch) return;
  state.chunks = job.chunks;
  state.pronunciation = job.pronunciation;
  if (job.state === 'error') throw new Error(job.error || 'โมเดลเสียงทำงานไม่สำเร็จ');
  if (job.state === 'cancelled') { state.jobId = undefined; schedule(generation); return; }
  const chunk = state.chunks[state.index];
  if (!chunk?.ready) {retries=0; state.status = 'buffering'; publish(); schedule(generation); return;}
  state.status = 'buffering'; publish();
  const blob = await audioBlob(state.settings.token, `/jobs/${state.jobId}/chunks/${state.index}`, controller.signal);
  if (generation !== epoch) return;
  disposeAudio();
  objectUrl = URL.createObjectURL(blob);
  restoringOffset = state.offset;
  audio.playbackRate = state.settings.rate;
  audio.volume = state.settings.volume;
  audio.onloadedmetadata = () => {
    if (generation !== epoch) return;
    audio.currentTime = Math.min(restoringOffset, Math.max(0, audio.duration - .05));
    void audio.play().then(() => {
      if (generation !== epoch) {audio.pause(); return;}
      state.status = 'playing'; state.error = ''; publish();
      retries=0;
      void syncBgm(generation);
    }).catch(error => {if (generation === epoch) fail(error);});
  };
  audio.onended = () => {
    if (generation !== epoch) return;
    state.offset = 0;
    if (state.index + 1 >= state.chunks.length) {
      interrupt(false); disposeAudio(); state.status = 'ended'; publish();
      void chrome.runtime.sendMessage({target: 'worker', type: 'CHAPTER_ENDED', snapshot: copy()}).then(response => {
        if (!response?.ok) fail(new Error(response?.error || 'ต่อบทไม่สำเร็จ'));
      }).catch(fail);
    } else {
      state.index++; state.status = 'buffering'; publish();
      void step(generation).catch(error => stepError(error,generation));
    }
  };
  audio.src = objectUrl;
}
audio.addEventListener('timeupdate', () => {
  if (state.status !== 'playing') return;
  state.offset = audio.currentTime;
  if (Date.now() - checkpoint > 2000) {checkpoint = Date.now(); publish();}
});
audio.addEventListener('error', () => {if (audio.getAttribute('src') && state.status === 'playing') fail(new Error('เล่นไฟล์เสียงไม่สำเร็จ'));});

function play() {
  if (!state.chapter) throw new Error('กดอ่านบทนี้ก่อน');
  if (state.status === 'playing' || state.status === 'buffering') return;
  const generation = interrupt(false);
  if (state.status === 'ended') {state.index = 0; state.offset = 0;}
  state.status = 'buffering'; state.error = ''; publish();
  void step(generation).catch(error => stepError(error,generation));
}
async function load(chapter: Chapter, config?: Settings, resume?: any) {
  interrupt(true); disposeAudio();
  state = emptySnapshot(config || state.settings);
  state.chapter = chapter;
  if (resume && resume.speechHash === await hashValue(speechSettings(state.settings))
      && resume.contentHash === chapter.contentHash) {
    state.index = resume.index; state.offset = resume.offset;
  }
  play();
}
async function handle(message: any) {
  switch (message.type) {
    case 'RESTORE':
      interrupt(false); disposeAudio();
      state = message.snapshot ?? emptySnapshot(message.settings);
      state.settings = {...defaults, ...message.settings};
      state.jobId = undefined; state.status = state.chapter ? 'paused' : 'idle';
      publish(); return copy();
    case 'GET_STATE': return copy();
    case 'SOURCE_TAB': if(state.chapter && state.chapter.url===message.url) state.chapter.tabId=message.tabId; publish(); return copy();
    case 'LOAD': await load(message.chapter, message.settings, message.resume); return copy();
    case 'ERROR': fail(new Error(message.error)); return copy();
    case 'SETTINGS': {
      const changed = state.settings.token !== message.settings.token || JSON.stringify(speechSettings(state.settings)) !== JSON.stringify(speechSettings(message.settings));
      const wasActive = state.status === 'playing' || state.status === 'buffering';
      const paragraph = state.chunks[state.index]?.paragraph ?? 0;
      if (changed) {interrupt(true); disposeAudio();}
      state.settings = message.settings;
      audio.playbackRate = state.settings.rate; audio.volume = state.settings.volume;
      bgmAudio.volume = Math.max(0, Math.min(1, state.settings.bgmVolume ?? 0.2));
      if (!state.settings.bgmEnabled || state.settings.bgmVolume <= 0) stopBgm();
      else if (state.status === 'playing' && !changed) void syncBgm(epoch);
      if (changed && state.chapter) {
        state.offset = 0; state.status = 'paused';
        // Segmentation is independent of dictionary and voice, so this index
        // still refers to the same paragraph. Reset audio, keep reading place.
        state.index = Math.max(0, state.chunks.findIndex(c => c.paragraph === paragraph));
        if (wasActive) play();
      }
      publish(); return copy();
    }
    case 'CONTROL': {
      switch (message.action) {
        case 'play': play(); break;
        case 'pause':
          if (state.status === 'playing') state.offset = audio.currentTime;
          interrupt(false); state.status = 'paused'; publish(); break;
        case 'stop':
          interrupt(true); disposeAudio(); state.offset = 0; state.status = 'stopped'; state.error = ''; publish(); break;
        case 'clear':
          interrupt(true); disposeAudio(); state = emptySnapshot(state.settings); publish(); break;
        case 'previous': case 'next': case 'seek': {
          if (!state.chapter || !state.chunks.length) break;
          let index = message.action === 'seek' ? state.chunks.findIndex(c => c.paragraph === Number(message.paragraph))
            : state.index + (message.action === 'next' ? 1 : -1);
          index = Math.max(0, Math.min(state.chunks.length - 1, index));
          interrupt(false); disposeAudio(); state.index = index; state.offset = 0; state.status = 'paused'; play(); break;
        }
      }
      return copy();
    }
  }
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (message.target !== 'player' || sender.id !== chrome.runtime.id || !sender.url?.startsWith(chrome.runtime.getURL(''))) return;
  handle(message).then(value => respond({ok: true, value})).catch(error => respond({ok: false, error: error.message}));
  return true;
});
