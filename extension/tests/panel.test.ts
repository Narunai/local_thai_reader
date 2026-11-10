// @vitest-environment jsdom
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {beforeEach, afterEach, expect, it, vi} from 'vitest';
import {defaults, emptySnapshot} from '../src/types';

let saved: any;
let keyConfigured: boolean;
let calls: any[];
const field = (id: string) => document.getElementById(id) as HTMLInputElement;
const flush = async () => {for(let i=0;i<70;i++) await Promise.resolve();};
beforeEach(async () => {
  vi.resetModules();
  saved = {...defaults, token:'local-test-token'}; keyConfigured = false; calls=[];
  document.body.innerHTML = readFileSync(path.resolve('panel.html'), 'utf8');
  HTMLElement.prototype.scrollIntoView = vi.fn(); window.scrollTo = vi.fn();
  vi.stubGlobal('chrome', {runtime:{onMessage:{addListener:vi.fn()},sendMessage:vi.fn(async (message:any)=>{
    calls.push(structuredClone(message));
    const value = (()=>{
      switch(message.type) {
        case 'SETTINGS_GET': return saved;
        case 'GET_STATE': return emptySnapshot(saved);
        case 'SETTINGS_SAVE': saved=structuredClone(message.settings); return emptySnapshot(saved);
        case 'HEALTH': return {health:{status:'ok'},voices:[{id:defaults.voice, name:'Test',ready:true}]};
        case 'GEMINI_STATUS': return {key_configured:keyConfigured,revision:keyConfigured?'test-revision':''};
        case 'GEMINI_KEY_SAVE': keyConfigured=true;return {key_configured:true,revision:'test-revision'};
        case 'GEMINI_KEY_DELETE': keyConfigured=false;return {key_configured:false,revision:''};
        case 'GEMINI_TEST': return {model:message.model,text:'Legendary',speech:'เลเจนดารี'};
      }
    })();
    return {ok:true,value};
  })}});
  await import('../src/panel'); await flush();
});
afterEach(()=>vi.unstubAllGlobals());

it('keeps cloud opt-in off and saves the key outside extension settings before enabling',async()=>{
  expect(field('gemini-enabled').checked).toBe(false);
  field('gemini-enabled').checked=true;
  field('gemini-batches').value='3';
  field('gemini-key').value='fake-api-key-for-test';
  field('save').click(); await flush();
  expect(saved.geminiEnabled).toBe(true);
  expect(saved.geminiModel).toBe('gemini-3.5-flash-lite');
  expect(saved.geminiBatches).toBe(3);
  expect(saved.geminiRevision).toBe('test-revision');
  expect(JSON.stringify(saved)).not.toContain('fake-api-key-for-test');
  expect(field('gemini-key').value).toBe('');
  expect(calls.findIndex(m=>m.type==='GEMINI_KEY_SAVE')).toBeLessThan(calls.findIndex(m=>m.type==='SETTINGS_SAVE'&&m.settings.geminiEnabled));
});

it('requires a key to opt in and can test a saved key without enabling cloud narration',async()=>{
  field('gemini-enabled').checked=true; field('save').click(); await flush();
  expect(saved.geminiEnabled).toBe(false);
  expect(field('error').textContent).toContain('API key');
  field('gemini-key').value='fake-api-key-for-test';
  field('gemini-test').click(); await flush();
  expect(field('gemini-result').textContent).toContain('เลเจนดารี');
  expect(saved.geminiEnabled).toBe(false);
});

it('disables cloud narration before deleting a saved key',async()=>{
  field('gemini-enabled').checked=true;field('gemini-key').value='fake-api-key-for-test';
  field('save').click();await flush();
  calls=[];
  field('gemini-clear').click();await flush();
  expect(saved.geminiEnabled).toBe(false);
  expect(keyConfigured).toBe(false);
  expect(calls.findIndex(m=>m.type==='SETTINGS_SAVE'&&!m.settings.geminiEnabled)).toBeLessThan(calls.findIndex(m=>m.type==='GEMINI_KEY_DELETE'));
});

it('shows the actual failure beside the test button including errors before the request',async()=>{
  vi.mocked(chrome.runtime.sendMessage).mockImplementation(async (message:any)=>{
    if(message.type==='GEMINI_TEST') return {ok:false,error:'Gemini: เกินโควตา (HTTP 429)'};
    return {ok:true,value:{key_configured:true,revision:'test-revision'}};
  });
  field('gemini-test').click(); await flush();
  expect(field('gemini-result').textContent).toContain('HTTP 429');
  expect(field('gemini-result').hidden).toBe(false);
  expect(field('gemini-result').dataset.kind).toBe('error');
  field('gemini-model').value='invalid model';
  field('gemini-test').click(); await flush();
  expect(field('gemini-result').textContent).toContain('ชื่อโมเดลไม่ถูกต้อง');
  expect(field('gemini-test').disabled).toBe(false);
});

it('clears a loaded chapter when clicking clear-chapter button',async()=>{
  expect(field('clear-chapter').disabled).toBe(true);
  const loaded = {...emptySnapshot(saved), chapter:{title:'บททดสอบ',url:'https://og-thai.blogspot.com/1.html',paragraphs:['ย่อหน้าแรก'],nextUrl:null}, status:'playing'};
  vi.mocked(chrome.runtime.sendMessage).mockImplementation(async (message:any)=>{
    calls.push(structuredClone(message));
    if(message.type==='LOAD') return {ok:true,value:loaded};
    if(message.type==='CONTROL' && message.action==='clear') return {ok:true,value:emptySnapshot(saved)};
    return {ok:true,value:emptySnapshot(saved)};
  });
  field('load').click(); await flush();
  expect(field('clear-chapter').disabled).toBe(false);
  expect(document.getElementById('chapter-title')?.textContent).toBe('บททดสอบ');
  field('clear-chapter').click(); await flush();
  expect(calls.some(m=>m.type==='CONTROL' && m.action==='clear')).toBe(true);
  expect(field('clear-chapter').disabled).toBe(true);
  expect(document.getElementById('chapter-title')?.textContent).toBe('เรื่องต่อไป เริ่มที่นี่');
  expect(document.getElementById('paragraph')?.textContent).toContain('ยังไม่มีเนื้อหา');
});
