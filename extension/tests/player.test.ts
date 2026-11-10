// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defaults, emptySnapshot } from '../src/types';
import { request, audioBlob } from '../src/api';

vi.mock('../src/api', () => ({request: vi.fn(), audioBlob: vi.fn()}));
let listener: any;
let audio: TestAudio;
class TestAudio {
  currentTime = 0; duration = 5; playbackRate = 1; volume = 1;
  preservesPitch = true;
  onloadedmetadata: (() => void) | null = null;
  onended: (() => void) | null = null;
  source = '';
  play = vi.fn(async () => {});
  pause = vi.fn();
  constructor() {audio = this;}
  set src(value: string) {this.source = value; queueMicrotask(() => this.onloadedmetadata?.());}
  get src() {return this.source;}
  removeAttribute() {this.source = '';}
  getAttribute() {return this.source;}
  load() {}
  addEventListener() {}
}
const chunk = {index:0, paragraph:0, text:'ทดสอบเสียง', ready:true, seconds:5};
const chapter = {title:'บททดสอบ',url:'https://og-thai.blogspot.com/1.html',paragraphs:['ทดสอบเสียง'],nextUrl:null};
const send = (type:string, extra:object = {}) => new Promise<any>((resolve, reject) => {
  listener({target:'player',type,...extra}, {id:'test',url:'chrome-extension://test/worker.js'}, (r:any) => r.ok ? resolve(r.value) : reject(new Error(r.error)));
});
const flush = async () => {for(let i=0;i<20;i++) await Promise.resolve();};
beforeEach(async () => {
  vi.useFakeTimers();
  vi.resetModules(); vi.clearAllMocks();
  vi.stubGlobal('Audio', TestAudio);
  vi.stubGlobal('chrome', {runtime:{id:'test',getURL:(p:string)=>`chrome-extension://test/${p}`,onMessage:{addListener:(fn:any)=>{listener=fn;}},sendMessage:vi.fn().mockResolvedValue({ok:true})}});
  URL.createObjectURL = vi.fn(()=>'blob:test'); URL.revokeObjectURL=vi.fn();
  let number=0;
  vi.mocked(request).mockImplementation(async (_token, path, options) => {
    if(path==='/jobs') return {id:`job${++number}`,state:'complete',chunks:[chunk]};
    if(path.endsWith('/cursor') || options?.method==='DELETE') return {ok:true};
    return {id:'job',state:'complete',chunks:[chunk]};
  });
  vi.mocked(audioBlob).mockResolvedValue(new Blob(['wave']));
  await import('../src/offscreen');
  await send('RESTORE',{snapshot:emptySnapshot({...defaults,token:'test-token'}),settings:{...defaults,token:'test-token'}});
});
afterEach(()=>{vi.clearAllTimers();vi.useRealTimers();vi.unstubAllGlobals();});
describe('audio session cancellation',()=>{
  it('sends cloud pronunciation only after opt-in and cancels the old job when disabled',async()=>{
    await send('SETTINGS',{settings:{...defaults,token:'test-token',geminiEnabled:true}});
    await send('LOAD',{chapter}); await flush();
    const cloud = vi.mocked(request).mock.calls.find(call=>call[1]==='/jobs');
    expect(JSON.parse(cloud![2]!.body as string).gemini).toEqual({enabled:true,model:'gemini-3.5-flash-lite',batches:4});
    vi.mocked(request).mockClear();
    await send('SETTINGS',{settings:{...defaults,token:'test-token'}}); await flush();
    expect(vi.mocked(request).mock.calls.some(call=>call[2]?.method==='DELETE')).toBe(true);
    const local = vi.mocked(request).mock.calls.find(call=>call[1]==='/jobs');
    expect(JSON.parse(local![2]!.body as string).gemini.enabled).toBe(false);
  });
  it('releases an idle document after 30 seconds',async()=>{
    await vi.advanceTimersByTimeAsync(30001);
    expect(chrome.runtime.sendMessage).toHaveBeenCalledWith({target:'worker',type:'CLOSE_IDLE'});
  });
  it('keeps a buffering player alive while a cold model takes over 30 seconds',async()=>{
    let release!: (value:Blob)=>void;
    vi.mocked(audioBlob).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
    await send('LOAD',{chapter}); await flush();
    vi.mocked(chrome.runtime.sendMessage).mockClear();
    await vi.advanceTimersByTimeAsync(35000);
    expect(chrome.runtime.sendMessage).not.toHaveBeenCalledWith({target:'worker',type:'CLOSE_IDLE'});
    release(new Blob(['audio'])); await flush();
    expect(audio.play).toHaveBeenCalledTimes(1);
  });
  it('recovers a transient audio connection failure without losing the session',async()=>{
    vi.mocked(audioBlob).mockRejectedValueOnce(Object.assign(new Error('temporary network failure'),{transient:true}));
    await send('LOAD',{chapter}); await flush();
    expect((await send('GET_STATE')).status).toBe('buffering');
    await vi.advanceTimersByTimeAsync(1001); await flush();
    expect(audio.play).toHaveBeenCalledTimes(1);
    expect((await send('GET_STATE')).chapter.url).toBe(chapter.url);
  });
  it('does not play an audio response that arrives after Stop',async()=>{
    let release!: (value:Blob)=>void;
    vi.mocked(audioBlob).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
    await send('LOAD',{chapter}); await flush();
    await send('CONTROL',{action:'stop'});
    release(new Blob(['old audio'])); await flush();
    expect(audio.play).not.toHaveBeenCalled();
    expect((await send('GET_STATE')).status).toBe('stopped');
  });
  it('ignores old audio when a new chapter replaces it',async()=>{
    let release!: (value:Blob)=>void;
    vi.mocked(audioBlob).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
    await send('LOAD',{chapter}); await flush();
    await send('LOAD',{chapter:{...chapter,title:'บทใหม่',url:'https://og-thai.blogspot.com/2.html'}}); await flush();
    expect(audio.play).toHaveBeenCalledTimes(1);
    release(new Blob(['old audio'])); await flush();
    expect(audio.play).toHaveBeenCalledTimes(1);
    expect((await send('GET_STATE')).chapter.title).toBe('บทใหม่');
  });
  it('pauses during buffering and resumes without stale playback',async()=>{
    let release!: (value:Blob)=>void;
    vi.mocked(audioBlob).mockImplementationOnce(()=>new Promise(resolve=>{release=resolve;}));
    await send('LOAD',{chapter}); await flush();
    await send('CONTROL',{action:'pause'});
    release(new Blob(['old audio'])); await flush();
    expect(audio.play).not.toHaveBeenCalled();
    await send('CONTROL',{action:'play'}); await flush();
    expect(audio.play).toHaveBeenCalledTimes(1);
  });
  it('clears the current chapter and cancels the active job',async()=>{
    await send('LOAD',{chapter}); await flush();
    expect((await send('GET_STATE')).chapter?.title).toBe('บททดสอบ');
    vi.mocked(request).mockClear();
    const cleared = await send('CONTROL',{action:'clear'});
    expect(cleared.chapter).toBeNull();
    expect(cleared.chunks).toEqual([]);
    expect(cleared.status).toBe('idle');
    expect(vi.mocked(request).mock.calls.some(call=>call[2]?.method==='DELETE')).toBe(true);
  });
});
