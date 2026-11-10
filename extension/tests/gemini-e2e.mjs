// Real Chromium + isolated FastAPI; Google is replaced by httpx.MockTransport.
// Does not touch the user's server, pairing token, keys, or browser profile.
import {spawn} from 'node:child_process';
import {cp, mkdir, mkdtemp, readFile, readdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = path.resolve(import.meta.dirname, '..');
const tts = path.resolve(root, '../local-tts');
const cacheBase = process.env.NOVEL_CACHE_HOME || 'D:/AI_Cache';
process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(cacheBase, 'playwright');
process.env.TEMP = path.join(cacheBase, 'temp'); process.env.TMP = process.env.TEMP;
await mkdir(path.join(cacheBase,'browser-profiles'), {recursive:true});
const scratch = await mkdtemp(path.join(cacheBase,'browser-profiles/gemini-e2e-'));
const dist = path.join(scratch, 'dist');
await cp(path.join(root,'dist'), dist, {recursive:true});
async function patchUrls(folder) {
  for(const item of await readdir(folder,{withFileTypes:true})) {
    const file = path.join(folder,item.name);
    if(item.isDirectory()) await patchUrls(file);
    else if(/\.(js|json)$/.test(item.name)) {
      const text = await readFile(file,'utf8');
      await writeFile(file,text.replaceAll('127.0.0.1:8765','127.0.0.1:8766'));
    }
  }
}
await patchUrls(dist);
const fixture = String.raw`
import json,os
from pathlib import Path
import httpx,numpy as np,soundfile as sf,uvicorn
from app.main import create_app
from app.engine import Engine
from app.pronunciation import GeminiPronouncer
from app.settings import ROOT
ROOT.mkdir(parents=True,exist_ok=True)
class Backend:
    current=''
    device='fixture'
    def unload(self): self.current=''
    def fingerprint(self,voice): return voice
    def synthesize(self,voice,text,output):
        self.current=voice
        with (ROOT/'synthesized.jsonl').open('a',encoding='utf-8') as f: f.write(json.dumps(text,ensure_ascii=False)+'\n')
        sf.write(output,np.zeros(16000*8),16000)
def factory(key,model):
    def handler(request):
        with (ROOT/'requests.jsonl').open('a',encoding='utf-8') as f: f.write(model+'\n')
        if model=='gemini-test-error': return httpx.Response(429,text='do not echo key')
        text=json.loads(json.loads(request.content)['contents'][0]['parts'][0]['text'])['text']
        hints=[{'source':k,'reading':v} for k,v in {'ลอเอล':'ลอ เอล','Legendary':'เลเจนดารี'}.items() if k in text]
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps({'replacements':hints})}]}}]})
    return GeminiPronouncer(key,model,transport=httpx.MockTransport(handler))
engine=Engine(Backend(),ROOT/'cache')
app=create_app(engine,'test-pairing-token',catalog=lambda:[{'id':'thonburian:reference','name':'Test narrator','ready':True}],pronouncer_factory=factory)
uvicorn.run(app,host='127.0.0.1',port=8766,access_log=False)
`;
const server = spawn(path.join(tts,'.venv/Scripts/python.exe'),['-X','utf8','-c',fixture],{
  cwd:tts, windowsHide:true, stdio:['ignore','pipe','pipe'], env:{...process.env,NOVEL_TTS_HOME:path.join(scratch,'tts')}
});
let logs='';server.stdout.on('data',b=>logs+=b);server.stderr.on('data',b=>logs+=b);
const {chromium}=await import('playwright');
let context;
const report={tests:[],errors:[],google_calls_mocked:true};
const push=report.tests.push.bind(report.tests);
report.tests.push=(message)=>{console.log('PASS: '+message);return push(message);};
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function until(fn) {
  for(let i=0;i<100;i++){if(await fn())return;await pause(100);}
  throw new Error('Timed out');
}
try {
  await until(()=>fetch('http://127.0.0.1:8766/health',{headers:{Authorization:'Bearer test-pairing-token'}}).then(r=>r.ok).catch(()=>false));
  context=await chromium.launchPersistentContext(path.join(scratch,'profile'),{channel:'chromium',headless:true,viewport:{width:420,height:1100},
    args:[`--disable-extensions-except=${dist}`,`--load-extension=${dist}`,'--autoplay-policy=no-user-gesture-required']});
  await context.route('https://og-thai.blogspot.com/**',route=>route.fulfill({contentType:'text/html; charset=utf-8',body:'<meta charset="utf-8"><h3 class="post-title">ทดสอบคำอ่าน</h3><div class="post-body"><p>ลอเอลได้รับไอเทม Legendary จำนวน 12 ชิ้น</p></div>'}));
  const worker=context.serviceWorkers()[0]||await context.waitForEvent('serviceworker');
  const id=new URL(worker.url()).host;
  const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));
  await page.goto(`chrome-extension://${id}/panel.html`);
  await page.locator('#settings:not([hidden])').waitFor();
  await page.locator('#token').fill('test-pairing-token');
  await page.locator('#gemini-enabled').check();
  await page.locator('#gemini-batches').selectOption('3');
  await page.locator('#gemini-key').fill('fake-gemini-key-for-browser-test');
  await page.locator('#dictionary').fill('ลอเอล=ลอ เอ็ล');
  await page.locator('#save').click();
  await page.locator('#settings').waitFor({state:'hidden'});
  assert.equal(await page.locator('#gemini-key').inputValue(),'');
  const data=await page.evaluate(()=>chrome.storage.local.get(null));
  assert(!JSON.stringify(data).includes('fake-gemini-key-for-browser-test'));
  assert.equal(data.settings.geminiEnabled,true);
  assert.equal(data.settings.geminiBatches,3);
  report.tests.push('Save opt-in and server key; key absent from all Chrome storage');
  await page.locator('#settings-toggle').click();
  await page.locator('#gemini-test').click();
  await until(async()=>(await page.locator('#gemini-result').textContent()).includes('เลเจนดารี'));
  report.tests.push('Test button renders returned pronunciation preview');
  await page.reload();
  await until(async()=>await page.locator('#connection').evaluate(e=>e.classList.contains('connected')));
  await page.locator('#settings-toggle').click();
  assert(await page.locator('#gemini-enabled').isChecked());
  assert.equal(await page.locator('#gemini-key').inputValue(),'');
  report.tests.push('Settings persist across panel reload without revealing API key');
  await page.locator('#gemini-model').fill('gemini-test-error');
  await page.locator('#gemini-test').click();
  await until(async()=>(await page.locator('#error').textContent()).includes('429'));
  assert(!(await page.locator('#error').textContent()).includes('fake-gemini-key'));
  await page.locator('#gemini-model').fill('gemini-3.5-flash-lite');
  report.tests.push('Quota failure is visible and sanitized');
  const novel=await context.newPage();await novel.goto('https://og-thai.blogspot.com/test.html');await novel.bringToFront();
  const send=async(type,extra={})=>page.evaluate(async({type,extra})=>{
    const r=await chrome.runtime.sendMessage({target:'worker',type,...extra});if(!r?.ok)throw new Error(r?.error);return r.value;
  },{type,extra});
  await send('LOAD');
  await until(async()=>(await send('GET_STATE')).status==='playing');
  const synthesized=await readFile(path.join(scratch,'tts/synthesized.jsonl'),'utf8');
  assert(synthesized.includes('ลอ เอ็ลได้รับไอเทม เลเจนดารี'));
  assert.equal((await send('GET_STATE')).chunks[0].text,'ลอเอลได้รับไอเทม Legendary จำนวน 12 ชิ้น');
  assert.deepEqual((await send('GET_STATE')).pronunciation,{total_batches:1,ready_batches:1});
  await send('CONTROL',{action:'stop'});
  report.tests.push('Reading pipeline applies Gemini edits and manual overrides; original display stays intact');
  await page.bringToFront();
  await page.locator('#gemini-clear').click();
  await until(async()=>(await send('SETTINGS_GET')).geminiEnabled===false);
  await until(async()=>(await page.locator('#gemini-result').textContent()).includes('ลบ API key'));
  await page.locator('#gemini-enabled').check();
  await page.locator('#save').click();
  await until(async()=>(await page.locator('#error').textContent()).includes('API key'));
  assert.equal((await send('SETTINGS_GET')).geminiEnabled,false);
  await page.locator('#gemini-enabled').uncheck();
  const requestsBefore=await readFile(path.join(scratch,'tts/requests.jsonl'),'utf8');
  await novel.bringToFront();await send('LOAD');await until(async()=>(await send('GET_STATE')).status==='playing');
  await send('CONTROL',{action:'stop'});
  assert.equal(await readFile(path.join(scratch,'tts/requests.jsonl'),'utf8'),requestsBefore);
  report.tests.push('Deleting the key disables cloud; local reading continues with zero Google calls');
  await page.bringToFront();await page.locator('.gemini-settings').scrollIntoViewIfNeeded();
  await page.screenshot({path:path.join(root,'reports/gemini-settings.png')});
  assert.deepEqual(report.errors,[]);report.status='passed';
} catch(e) {
  report.status='failed';report.errors.push(e.message);console.error(logs);throw e;
} finally {
  if(context)await context.close();server.kill();
  await writeFile(path.join(root,'reports/gemini-e2e.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
}
