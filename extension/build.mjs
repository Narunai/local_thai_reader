import {build} from 'esbuild';
import {readFile, writeFile, mkdir, rm, realpath} from 'node:fs/promises';
import {watch} from 'node:fs';
import path from 'node:path';

const root=import.meta.dirname;
const dist=path.join(root,'dist');
const publicDir=path.join(root,'public');

async function compile() {
  // Build in memory first. Never delete a loaded extension before compilation
  // succeeds. Each script is self-contained; Chrome needs no dev server/imports.
  const entries={
    'reader-background':'src/background.ts',
    'reader-runtime':'src/worker.ts',
    panel:'src/panel.ts',
    offscreen:'src/offscreen.ts',
  };
  const result=await build({
    absWorkingDir:root,entryPoints:entries,outdir:dist,
    bundle:true,format:'iife',target:'chrome116',minify:true,write:false,
  });
  const manifest=JSON.parse(await readFile(path.join(publicDir,'manifest.json'),'utf8'));
  const files=new Map(result.outputFiles.map(f=>[path.basename(f.path),f.contents]));
  files.set('panel.html',await readFile(path.join(root,'panel.html')));
  files.set('offscreen.html',await readFile(path.join(root,'offscreen.html')));
  files.set('panel.css',await readFile(path.join(root,'src/panel.css')));
  for(const folder of [dist,publicDir]){
    await mkdir(folder,{recursive:true});
    for(const [name,content] of files)await writeFile(path.join(folder,name),content);
  }
  // Publish manifests last. Root/public remain compatible with earlier installs.
  await writeFile(path.join(dist,'manifest.json'),JSON.stringify(manifest,null,2)+'\n');
  const rootManifest=structuredClone(manifest);
  rootManifest.background.service_worker='dist/'+manifest.background.service_worker;
  rootManifest.side_panel.default_path='dist/'+manifest.side_panel.default_path;
  await writeFile(path.join(root,'manifest.json'),JSON.stringify(rootManifest,null,2)+'\n');
  // Check the exact package Chrome will load, including the runtime script.
  for(const name of [manifest.background.service_worker,manifest.side_panel.default_path,'reader-runtime.js','offscreen.html','panel.js','panel.css']){
    if(!files.has(name))throw new Error(`Missing extension file: ${name}`);
  }
  // Remove only known artifacts from the former Vite build. Resolve and verify
  // each directory stays in this project before any recursive removal.
  for(const folder of [dist,publicDir]){
    const actual=await realpath(folder);
    const relative=path.relative(root,actual);
    if(relative.startsWith('..') || path.isAbsolute(relative))throw new Error('Build directory leaves project');
    for(const name of ['assets','sw.js','worker.js']){
      const target=path.resolve(actual,name);
      if(path.dirname(target)!==actual)throw new Error('Unsafe legacy artifact path');
      await rm(target,{recursive:true,force:true});
    }
  }
  console.log(`Built Chrome extension ${manifest.version}: ${dist}`);
}

await compile();
if(process.argv.includes('--watch')){
  let timer,running=false,again=false;
  async function update(){
    if(running){again=true;return;}
    running=true;
    do{again=false;try{await compile();}catch(error){console.error(error);}}while(again);
    running=false;
  }
  const changed=()=>{clearTimeout(timer);timer=setTimeout(update,150);};
  watch(path.join(root,'src'),{recursive:true},changed);
  for(const name of ['panel.html','offscreen.html'])watch(path.join(root,name),changed);
}
