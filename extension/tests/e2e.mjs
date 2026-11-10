// Real Chromium extension + real local TTS. Run after npm run build.
import { readFile, writeFile, mkdir, mkdtemp } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = path.resolve(import.meta.dirname, '..');
const tts = path.resolve(root, '../local-tts');
const reportDir = path.join(root, 'reports');
const cacheBase = process.env.NOVEL_CACHE_HOME || 'D:/AI_Cache';
process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(cacheBase, 'playwright');
process.env.TEMP = path.join(cacheBase, 'temp');
process.env.TMP = process.env.TEMP;
const { chromium } = await import('playwright');
await mkdir(path.join(cacheBase, 'browser-profiles'), {recursive:true});
await mkdir(process.env.TEMP, {recursive:true});
await mkdir(reportDir, {recursive: true});
const token = (await readFile(path.join(tts, '.token'), 'utf8')).trim();
const server = spawn(path.join(tts, '.venv/Scripts/python.exe'), ['-X','utf8','-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8765','--no-access-log'], {cwd:tts, windowsHide:true, stdio:['ignore','pipe','pipe']});
let serverLog = '';
server.stdout.on('data', data => {serverLog += data.toString();});
server.stderr.on('data', data => {serverLog += data.toString();});
const report = {tests: [], errors: [], started: new Date().toISOString()};
const originalPush = report.tests.push.bind(report.tests);
report.tests.push = (...items) => {items.forEach(item=>console.log('PASS: '+item)); return originalPush(...items);};
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
let context;
const profileDir = await mkdtemp(path.join(cacheBase,'browser-profiles/novel-e2e-'));
const launchOptions = {
  channel:'chromium', headless:true, viewport:{width:400,height:1100},
  args:[`--disable-extensions-except=${path.join(root,'dist')}`,`--load-extension=${path.join(root,'dist')}`,'--autoplay-policy=no-user-gesture-required']
};
async function until(fn, timeout=30000) {
  const end=Date.now()+timeout;
  while(Date.now()<end) {const value=await fn(); if(value) return value; await pause(250);}
  throw new Error('Timed out waiting for test condition');
}
try {
  await until(async()=>fetch('http://127.0.0.1:8765/health', {headers:{Authorization:`Bearer ${token}`}}).then(r=>r.ok).catch(()=>false), 20000);
  context = await chromium.launchPersistentContext(profileDir, launchOptions);
  let worker=context.serviceWorkers()[0];
  if(!worker) worker=await context.waitForEvent('serviceworker');
  const id=new URL(worker.url()).host;
  let panel=await context.newPage();
  panel.on('pageerror',e=>report.errors.push(e.message));
  await panel.goto(`chrome-extension://${id}/panel.html`);
  const send=async(type,extra={})=>{
    const value=await panel.evaluate(async({type,extra})=>{
      const result=await chrome.runtime.sendMessage({target:'worker',type,...extra});
      if(!result?.ok) throw new Error(result?.error || 'No response');
      return result.value;
    },{type,extra});
    if(value?.status) report.lastSnapshot={status:value.status,error:value.error,index:value.index,offset:value.offset,url:value.chapter?.url,paragraphs:value.chapter?.paragraphs.length,jobId:value.jobId,ready:value.chunks?.filter(c=>c.ready).length};
    return value;
  };
  await panel.locator('#token').fill(token);
  await panel.locator('#save').click();
  await panel.locator('.connection.connected').waitFor();
  report.tests.push('Token pairing and health connection');
  let novel=await context.newPage();
  await novel.goto('https://og-thai.blogspot.com/2022/04/1221.html',{waitUntil:'domcontentloaded',timeout:45000});
  await novel.bringToFront();
  const available=await send('HEALTH');
  if(available.voices.some(v=>v.id==='thonburian:reference'&&v.ready)){
    const config=await send('SETTINGS_GET');
    await send('SETTINGS_SAVE',{settings:{...config,voice:'thonburian:reference'}});
    await send('LOAD');
    await until(async()=>{const s=await send('GET_STATE');if(s.status==='error')throw new Error(s.error);return s.status==='playing';},90000);
    await send('CONTROL',{action:'stop'});
    await send('SETTINGS_SAVE',{settings:{...config,voice:'vachana:th_f_1'}});
    report.tests.push('Thonburian CUDA synthesis and playback through the real API, then switch back to Vachana');
  }
  await send('LOAD');
  let current=await until(async()=>{const s=await send('GET_STATE'); if(s.status==='error') throw new Error(s.error); return s.status==='playing'?s:false;},45000);
  assert(current.chapter.title.includes('1,221'));
  assert(current.chapter.paragraphs.length>30);
  assert(!current.chapter.paragraphs.some(p=>p.includes('ขอบคุณ​มาก​ๆ​ครับ')));
  assert(current.chapter.nextUrl.endsWith('/1222.html'));
  report.liveChapter={paragraphs:current.chapter.paragraphs.length, chunks:current.chunks.length, nextUrl:current.chapter.nextUrl};
  report.tests.push('Live OG Thai extraction and real audio playback');
  await send('CONTROL',{action:'pause'});
  const paused=await send('GET_STATE');
  await pause(32000);
  current=await send('GET_STATE');
  assert.equal(current.status,'paused');
  assert.equal(current.index,paused.index);
  await send('CONTROL',{action:'play'});
  await until(async()=>(await send('GET_STATE')).status==='playing',45000);
  report.tests.push('Resume after 32-second pause / offscreen recreation');
  await send('CONTROL',{action:'seek',paragraph:3});
  current=await until(async()=>{const s=await send('GET_STATE');return s.status==='playing'&&s.chunks[s.index]?.paragraph===3?s:false;},45000);
  report.tests.push('Seek starts from requested paragraph');
  await send('CONTROL',{action:'stop'});
  const stopped=await send('GET_STATE');
  await pause(1200);
  assert.equal((await send('GET_STATE')).status,'stopped');
  report.tests.push('Stop discards pending playback');
  await panel.screenshot({path:path.join(reportDir,'panel.png'),fullPage:true});
  // Restore after actual browser restart using the same persisted profile.
  const saved=await panel.evaluate(()=>chrome.storage.local.get('snapshot'));
  assert.equal(saved.snapshot.chapter.url,stopped.chapter.url);
  await worker.evaluate(()=>chrome.offscreen.closeDocument());
  const restored=await send('GET_STATE');
  assert.equal(restored.status,'paused');
  assert.equal(restored.index,stopped.index);
  report.tests.push('Persisted position restores after offscreen is closed');
  await context.close();
  context=await chromium.launchPersistentContext(profileDir,launchOptions);
  panel=await context.newPage();
  await panel.goto(`chrome-extension://${id}/panel.html`);
  const afterRestart=await send('GET_STATE');
  assert.equal(afterRestart.status,'paused');
  assert.equal(afterRestart.index,stopped.index);
  assert.equal(afterRestart.chapter.url,stopped.chapter.url);
  report.tests.push('Position and paired settings survive a full browser restart');
  await send('CONTROL',{action:'play'});
  const resumed=await until(async()=>{const s=await send('GET_STATE');if(s.status==='error')throw new Error(s.error);return s.status==='playing'&&s.chapter.tabId?s:false;},45000);
  const attached=await until(async()=>{
    const tab=await panel.evaluate(id=>chrome.tabs.get(id),resumed.chapter.tabId);
    return tab.url===stopped.chapter.url&&tab.status==='complete'?tab:false;
  },30000);
  assert.equal(attached.url,stopped.chapter.url);
  await until(()=>panel.evaluate(async id=>(await chrome.scripting.executeScript({target:{tabId:id},func:()=>CSS.highlights.has('novel-reading')}))[0].result,resumed.chapter.tabId),10000);
  await send('CONTROL',{action:'stop'});
  report.tests.push('Resume reconnects to a current source tab after browser IDs change');
  novel=await context.newPage();
  // Tiny real model chapters exercise next-page navigation without reading the
  // entire copyrighted chapter during a development check.
  const page1='https://og-thai.blogspot.com/2022/04/1221.html';
  const page2='https://og-thai.blogspot.com/2022/04/1222.html';
  await novel.goto(page1,{waitUntil:'domcontentloaded',timeout:45000});
  await novel.bringToFront(); await send('LOAD');
  const real=(await send('GET_STATE')).chapter;
  await until(async()=>(await send('GET_STATE')).chunks.length>0,45000);
  await send('CONTROL',{action:'seek',paragraph:real.paragraphs.length-1});
  await until(async()=>{const s=await send('GET_STATE');if(s.status==='error')throw new Error(s.error);return s.chapter.url===page2&&s.chapter.paragraphs.length>30;},60000);
  await send('CONTROL',{action:'stop'});
  report.tests.push('Live final paragraph follows the actual OG Thai next link and extracts chapter 1,222');
  await context.route('https://og-thai.blogspot.com/**',route=>route.fulfill({contentType:'text/html',body:`<html><head><title>ทดสอบ</title></head><body><h3 class="post-title">ทดสอบ ${route.request().url().includes('1222')?'1,222':'1,221'}</h3><div class="post-body"><p>สวัสดีค่ะ ยินดีต้อนรับ</p><p>เราจะอ่านนิยายไปด้วยกัน</p></div>${route.request().url().includes('1222')?'':`<a class="newer-link" href="${page2}">Next</a>`}</body></html>`}));
  await novel.goto(page1); await novel.bringToFront(); await send('LOAD');
  await until(async()=>{const s=await send('GET_STATE');if(s.status==='error')throw new Error(s.error);return s.chapter.url===page2;},60000);
  await until(async()=>(await send('GET_STATE')).status==='ended',45000);
  report.tests.push('Automatic chapter 1,221 → 1,222 using next link, then stop at end');
  const minutes=Number(process.env.NOVEL_SOAK_MINUTES || '0');
  if(minutes>0){
    const soakVoice=process.env.NOVEL_SOAK_VOICE || 'vachana:th_f_1';
    const soakSettings=await send('SETTINGS_GET');
    await send('SETTINGS_SAVE',{settings:{...soakSettings,voice:soakVoice}});
    await novel.evaluate(()=>{
      document.querySelector('.post-body').innerHTML=Array.from({length:600},(_,i)=>`<p>ลำดับที่ ${i+1} สายลมอ่อนพัดผ่านหน้าต่าง เธอเปิดหนังสือเล่มเก่าอย่างช้า ๆ และยิ้มให้กับเรื่องราวที่กำลังจะเริ่มต้น</p>`).join('');
    });
    await novel.bringToFront(); await send('LOAD');
    const start=Date.now(); let last=-1; let transitions=0; let buffering=0; let playSeconds=0;
    while(Date.now()-start<minutes*60000){
      const s=await send('GET_STATE');
      assert.notEqual(s.status,'error',s.error); assert.notEqual(s.status,'ended');
      assert(['playing','buffering'].includes(s.status),`Unexpected soak status ${s.status}: ${s.error}`);
      assert(s.index>=last,'Playback moved backwards');
      if(s.index>last){transitions++;last=s.index;}
      if(s.status==='buffering') buffering++; else if(s.status==='playing') playSeconds++;
      if((playSeconds+buffering)%30===0){
        console.log(`SOAK ${Math.round((Date.now()-start)/1000)}s: index=${s.index}, status=${s.status}, transitions=${transitions}`);
        await writeFile(path.join(reportDir,'soak-progress.json'),JSON.stringify({elapsedSeconds:Math.round((Date.now()-start)/1000),index:s.index,status:s.status,transitions,playingPolls:playSeconds,bufferingPolls:buffering}));
      }
      await pause(1000);
    }
    await send('CONTROL',{action:'stop'});
    report.soak={voice:soakVoice,wallSeconds:Math.round((Date.now()-start)/1000),transitions,playingPolls:playSeconds,bufferingPolls:buffering};
    assert(transitions>minutes*3,'Too few chunks were played during soak');
    assert(playSeconds>minutes*40,'Audio did not play for enough of the soak');
    report.tests.push(`${minutes}-minute real audio soak with ordered chunks and no model errors`);
  }
  // Offline proof: all non-local network requests are denied after page load.
  await context.route('**/*',route=>route.request().url().startsWith('http://127.0.0.1:8765/')||route.request().url().startsWith('chrome-extension:')?route.continue():route.abort());
  await send('CONTROL',{action:'play'});
  await until(async()=>(await send('GET_STATE')).status==='playing',30000);
  await send('CONTROL',{action:'stop'});
  report.tests.push('Playback works while all external browser network requests are blocked');
  report.status='passed';
} catch(error) {
  report.status='failed'; report.failure=error.stack;
  process.exitCode=1;
} finally {
  await context?.close();
  server.kill();
  report.serverLog=serverLog;
  report.serverExitCode=server.exitCode;
  const safe = text => text.replaceAll(token,'[redacted]');
  await writeFile(path.join(reportDir,'e2e.json'),safe(JSON.stringify(report,null,2)));
  console.log(safe(JSON.stringify({status:report.status,tests:report.tests,failure:report.failure,errors:report.errors,lastSnapshot:report.lastSnapshot},null,2)));
}
