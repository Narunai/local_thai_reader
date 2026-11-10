// Test the real toolbar action in the same installed Google Chrome version as the user.
// Chrome's CDP extension API operates only in this fresh test profile on D.
import {mkdir,mkdtemp,readFile,writeFile,cp} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const root=path.resolve(import.meta.dirname,'..');
const cache=process.env.NOVEL_CACHE_HOME||'D:/AI_Cache';
process.env.TEMP=path.join(cache,'temp');process.env.TMP=process.env.TEMP;
await mkdir(path.join(cache,'browser-profiles'),{recursive:true});
const profile=await mkdtemp(path.join(cache,'browser-profiles/chrome-action-'));
const broken=process.argv.includes('--broken-runtime');
let extensionPath=path.join(root,'dist');
if(broken){
  extensionPath=await mkdtemp(path.join(cache,'browser-profiles/broken-runtime-'));
  await cp(path.join(root,'dist'),extensionPath,{recursive:true});
  await writeFile(path.join(extensionPath,'reader-runtime.js'),"throw new Error('TEST_RUNTIME_BOOT_FAILURE');");
}
const {chromium}=await import('playwright');
const context=await chromium.launchPersistentContext(profile,{
  executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:process.env.NOVEL_CHROME_HEADFUL!=='1',
  ignoreDefaultArgs:['--disable-extensions'],
  args:['--enable-unsafe-extension-debugging',...(process.env.NOVEL_CHROME_HEADFUL==='1'?['--start-minimized']:[])],
});
const manifest=JSON.parse(await readFile(path.join(root,'dist/manifest.json'),'utf8'));
const report={version:manifest.version,profile_isolated:true,google_calls:0,errors:[]};
try {
  const session=await context.browser().newBrowserCDPSession();
  report.browser=(await session.send('Browser.getVersion')).product;
  const {id}=await session.send('Extensions.loadUnpacked',{path:extensionPath});
  assert.equal(manifest.action.default_popup,undefined,'Toolbar must open a side panel, not a popup');
  const page=context.pages()[0]||await context.newPage();
  await page.goto('about:blank');
  await page.bringToFront();
  let worker=context.serviceWorkers()[0]||await context.waitForEvent('serviceworker');
  async function configured(){
    for(let i=0;i<100;i++){
      const state=await worker.evaluate(async()=>({
        options:await chrome.sidePanel.getOptions({}),
        behavior:await chrome.sidePanel.getPanelBehavior(),
        popup:await chrome.action.getPopup({}),
      }));
      if(state.options.enabled && state.behavior.openPanelOnActionClick && state.popup==='')return state;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    throw new Error('Native toolbar behavior was not restored');
  }
  async function clickAndCheck(label,restore=true){
    if(restore)await configured();
    const before=await worker.evaluate(()=>chrome.tabs.query({}));
    await page.bringToFront();
    const {targetInfos}=await session.send('Target.getTargets',{filter:[{type:'tab',exclude:false}]});
    const source=targetInfos.find(t=>t.url===page.url());
    assert(source,'Source tab target missing');
    await session.send('Extensions.triggerAction',{id,targetId:source.targetId});
    let contexts=[];
    for(let i=0;i<100;i++){
      contexts=await worker.evaluate(()=>chrome.runtime.getContexts({}));
      if(contexts.some(c=>c.contextType==='SIDE_PANEL'))break;
      await new Promise(resolve=>setTimeout(resolve,100));
    }
    assert(contexts.some(c=>c.contextType==='SIDE_PANEL'),'Toolbar click did not open SIDE_PANEL');
    assert(!contexts.some(c=>c.contextType==='POPUP'),'Unexpected popup');
    const targets=await session.send('Target.getTargets',{filter:[{}]});
    const panel=targets.targetInfos.find(t=>t.url===`chrome-extension://${id}/${manifest.side_panel.default_path}`);
    assert(panel,'Side panel target missing');
    const {sessionId}=await session.send('Target.attachToTarget',{targetId:panel.targetId,flatten:false});
    let serial=0;
    const pending=new Map();
    const onMessage=event=>{
      if(event.sessionId!==sessionId)return;
      const message=JSON.parse(event.message),p=pending.get(message.id);
      if(!p)return;
      pending.delete(message.id);
      if(message.error)p.reject(new Error(message.error.message));else p.resolve(message.result);
    };
    session.on('Target.receivedMessageFromTarget',onMessage);
    async function command(method,params={}){
      const commandId=++serial;
      const result=new Promise((resolve,reject)=>pending.set(commandId,{resolve,reject}));
      await session.send('Target.sendMessageToTarget',{sessionId,message:JSON.stringify({id:commandId,method,params})});
      let timer;
      try{return await Promise.race([result,new Promise((_,reject)=>timer=setTimeout(()=>reject(new Error('Panel command timed out')),10000))]);}
      finally{clearTimeout(timer);}
    }
    try{
      let ready=false;
      for(let i=0;i<50;i++){
        const r=await command('Runtime.evaluate',{expression:"Boolean(document.getElementById('settings-toggle'))",returnByValue:true});
        if(r.result.value){ready=true;break;}
        await new Promise(resolve=>setTimeout(resolve,100));
      }
      assert(ready,'Side panel UI did not render');
      const r=await command('Runtime.evaluate',{
        expression:"chrome.runtime.sendMessage({target:'worker',type:'GET_STATE'})",awaitPromise:true,returnByValue:true,
      });
      if(broken){
        assert.equal(r.result.value?.ok,false,'Broken engine must return a diagnostic');
        assert(r.result.value.error.includes('TEST_RUNTIME_BOOT_FAILURE'));
        const visible=await command('Runtime.evaluate',{
          expression:"document.getElementById('error').textContent",returnByValue:true,
        });
        assert(visible.result.value.includes('TEST_RUNTIME_BOOT_FAILURE'),'Startup error was not shown in the side panel');
      }else{
        assert.equal(r.result.value?.ok,true,'Side panel cannot reach the worker/player');
        assert.equal(r.result.value.value.status,'idle');
      }
      const after=await worker.evaluate(()=>chrome.tabs.query({}));
      assert.equal(after.length,before.length,'Toolbar created an unwanted tab');
      report[label]={side_panel_opened:true,controls_rendered:true,
        ...(broken?{startup_error_visible:true}:{player_connected:true}),no_popup:true,no_new_tab:true};
    } finally {
      session.off('Target.receivedMessageFromTarget',onMessage);
      await session.send('Target.detachFromTarget',{sessionId});
    }
  }
  report.stage='native-toolbar';
  await clickAndCheck('fresh_install');
  // Reproduce old persisted behavior, then reload as the user does after updating.
  await worker.evaluate(async()=>{
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    await chrome.sidePanel.close({windowId:tab.windowId});
    await chrome.storage.local.set({upgradeTestMarker:'preserve-settings'});
    await chrome.sidePanel.setOptions({enabled:false});
    await chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:false});
    await chrome.action.setPopup({popup:'panel.html'});
  });
  const nextWorker=context.waitForEvent('serviceworker',{predicate:w=>w.url()===worker.url(),timeout:15000});
  await session.send('Extensions.loadUnpacked',{path:extensionPath});
  worker=await nextWorker;
  report.stage='toolbar-after-reload';
  await clickAndCheck('after_reload');
  assert.equal(await worker.evaluate(async()=>(await chrome.storage.local.get('upgradeTestMarker')).upgradeTestMarker),'preserve-settings');
  report.settings_preserved=true;
  // The native toolbar flag may be missing after a failed startup. Verify
  // the registered click event itself still opens the panel without restoring it.
  await worker.evaluate(async()=>{
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    await chrome.sidePanel.close({windowId:tab.windowId});
    await chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:false});
  });
  report.stage='action-with-native-behavior-disabled';
  await clickAndCheck('explicit_action',false);
  report.status='passed';
  console.log(JSON.stringify(report,null,2));
} catch(error){
  report.status='failed';report.errors.push(error.message);console.log(JSON.stringify(report,null,2));
  process.exitCode=1;
} finally {
  await context.close();
  await writeFile(path.join(root,broken?'reports/bootstrap-failure-e2e.json':'reports/chrome-action-e2e.json'),JSON.stringify(report,null,2));
}
