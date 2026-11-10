import { defaults, type Settings, type Snapshot, type Voice } from './types';
const $ = <T extends HTMLElement = HTMLElement>(id: string) => document.getElementById(id) as T;
let config = {...defaults};
let snapshot: Snapshot | undefined;
let lastChapter = '';
let busy = false;
let playerErrorActive = false;
async function send(type: string, extra: object = {}, timeoutMs = 20000): Promise<any> {
  const response = await new Promise<any>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Extension ไม่ตอบกลับภายในเวลาที่กำหนด · กรุณากดรีโหลด Extension แล้วลองใหม่')), timeoutMs);
    chrome.runtime.sendMessage({target: 'worker', type, ...extra}).then(
      res => { clearTimeout(timer); resolve(res); },
      err => { clearTimeout(timer); reject(err); }
    );
  });
  if (!response?.ok) throw new Error(response?.error || 'Extension ไม่ตอบกลับ');
  return response.value;
}
function error(message = '', fromPlayer = false) {
  $('error').textContent = message; $('error').hidden = !message;
  playerErrorActive = fromPlayer && !!message;
}
async function run(action: () => Promise<any>) {
  error();
  try {return await action();} catch (e) {error((e as Error).message);}
}
function applySettings(value: Settings) {
  config = {...defaults, ...value};
  $<HTMLInputElement>('token').value = value.token;
  $<HTMLSelectElement>('voice').value = value.voice;
  $<HTMLInputElement>('rate').value = String(config.rate);
  $<HTMLInputElement>('volume').value = String(config.volume);
  const bgmEnabledEl = document.getElementById('bgm-enabled') as HTMLInputElement | null;
  if (bgmEnabledEl) bgmEnabledEl.checked = config.bgmEnabled;
  const bgmVolumeEl = document.getElementById('bgm-volume') as HTMLInputElement | null;
  if (bgmVolumeEl) bgmVolumeEl.value = String(config.bgmVolume);
  $<HTMLInputElement>('auto-next').checked = config.autoNext;
  $<HTMLInputElement>('auto-scroll').checked = config.autoScroll;
  $<HTMLTextAreaElement>('dictionary').value = Object.entries(config.dictionary).map(([k,v]) => `${k}=${v}`).join('\n');
  $<HTMLInputElement>('gemini-enabled').checked = config.geminiEnabled;
  $<HTMLInputElement>('gemini-model').value = config.geminiModel;
  $<HTMLSelectElement>('gemini-batches').value = String(config.geminiBatches);
  labels();
}
function labels() {
  $('rate-value').textContent = `${config.rate.toFixed(2)}×`;
  $('rate-label').textContent = `${config.rate.toFixed(2)}×`;
  $('volume-value').textContent = `${Math.round(config.volume * 100)}%`;
  const bgmVolOut = document.getElementById('bgm-volume-value');
  if (bgmVolOut) bgmVolOut.textContent = `${Math.round(config.bgmVolume * 100)}%`;
  $('privacy-text').textContent = config.geminiEnabled ? 'สร้างเสียงในเครื่อง · ส่งข้อความเตรียมคำอ่านไป Gemini' : 'สร้างเสียงในเครื่อง · Gemini ปิดอยู่';
}
function render(value: Snapshot) {
  snapshot = value;
  const names: Record<string,string> = {idle:'เปิดนิยายแล้วกด “อ่านบทนี้”', buffering:'กำลังเตรียมเสียงช่วงถัดไป…', playing:'กำลังเล่าให้ฟัง', paused:'พักไว้ · กดเล่นเพื่อฟังต่อ', stopped:'หยุดแล้ว · กดเล่นเพื่อฟังต่อ', ended:'อ่านจบบทแล้ว', error:'ระบบเสียงต้องการการตรวจสอบ'};
  $('status').textContent = names[value.status] ?? value.status;
  $('chapter-title').textContent = value.chapter?.title || 'เรื่องต่อไป เริ่มที่นี่';
  $('chapter-label').textContent = value.chapter ? `${value.chapter.paragraphs.length} ย่อหน้า` : 'ยังไม่ได้เลือกบท';
  $('current-text').textContent = value.chunks[value.index]?.text || 'ข้อความที่กำลังอ่านจะปรากฏตรงนี้';
  $('play').textContent = ['playing','buffering'].includes(value.status) ? 'Ⅱ' : '▶';
  const count = value.chunks.length;
  const current = value.chunks[value.index];
  const bgmEl = document.getElementById('bgm-status');
  if (bgmEl) {
    if (!value.settings.bgmEnabled) bgmEl.textContent = '♪ เพลงคลอ: ปิดอยู่';
    else if (current?.bgm?.label) bgmEl.textContent = `♪ เพลงคลอ: ${current.bgm.label}`;
    else bgmEl.textContent = '♪ เพลงคลอ: พร้อมเปลี่ยนตามอารมณ์เรื่อง';
  }
  const percent = value.status === 'ended' ? 100 : count ? (value.index + (current?.seconds ? value.offset / current.seconds : 0)) / count * 100 : 0;
  $('progress').style.width = `${percent}%`;
  const batchProgress = value.settings.geminiEnabled && value.pronunciation?.total_batches ? ` · คำอ่าน ${value.pronunciation.ready_batches}/${value.pronunciation.total_batches} ชุด` : '';
  $('progress-text').textContent = (count ? `ช่วง ${value.index+1} / ${count} · ย่อหน้า ${(current?.paragraph ?? 0)+1}` : 'พร้อมเมื่อคุณพร้อม') + batchProgress;
  const chapterKey = JSON.stringify([value.chapter?.url, value.chapter?.paragraphs]);
  const clearBtn = document.getElementById('clear-chapter') as HTMLButtonElement | null;
  if (clearBtn) clearBtn.disabled = !value.chapter;
  if (lastChapter !== chapterKey) {
    lastChapter = chapterKey;
    const select = $<HTMLSelectElement>('paragraph'); select.replaceChildren();
    if (!value.chapter?.paragraphs.length) {
      const option = document.createElement('option'); option.value = '0'; option.textContent = 'ยังไม่มีเนื้อหา'; select.append(option);
    } else {
      value.chapter.paragraphs.forEach((p, i) => {
        const option = document.createElement('option'); option.value = String(i); option.textContent = `${i+1}. ${p.slice(0,65)}`; select.append(option);
      });
    }
  }
  if (value.error) error(value.error, true);
  else if (playerErrorActive) error();
}
async function health() {
  try {
    const result = await send('HEALTH');
    $('connection').classList.add('connected');
    $('connection-text').textContent = config.geminiEnabled ? 'เชื่อมต่อแล้ว · ใช้ Gemini เตรียมคำอ่าน' : 'เชื่อมต่อแล้ว · เสียงบนเครื่อง';
    const select = $<HTMLSelectElement>('voice'); select.replaceChildren();
    (result.voices as Voice[]).forEach(voice => {
      const option = document.createElement('option'); option.value = voice.id; option.textContent = voice.name + (voice.ready ? '' : ' · ยังไม่ติดตั้ง'); option.disabled = !voice.ready; option.title = voice.reason; select.append(option);
    });
    select.value = config.voice;
    if (!result.voices.some((v: Voice) => v.id === config.voice && v.ready)) {
      const first = result.voices.find((v: Voice) => v.ready);
      if (first) {config.voice = first.id; select.value = first.id; await send('SETTINGS_SAVE', {settings: config});}
    }
    await refreshGeminiStatus();
  } catch (e) {
    $('connection').classList.remove('connected'); $('connection-text').textContent = 'ยังไม่เชื่อมต่อระบบเสียง';
    error((e as Error).message);
    if (!config.token) {
      $('settings').hidden = false;
      $('settings').scrollIntoView({behavior:'smooth', block:'start'});
    }
  }
}
async function saveSimple() {labels(); await send('SETTINGS_SAVE', {settings: config});}
async function refreshGeminiStatus() {
  try {
    const status = await send('GEMINI_STATUS');
    $('gemini-key-status').textContent = status.key_configured ? 'บันทึก API key ที่ Local Server แล้ว · เว้นว่างเพื่อใช้รหัสเดิม' : 'ยังไม่มี API key · รับจาก Google AI Studio แล้ววางในช่องนี้';
    return status;
  } catch (e) {
    $('gemini-key-status').textContent = (e as Error).message;
  }
}
async function syncToken() {
  const token = $<HTMLInputElement>('token').value.trim();
  if (token !== config.token) {config.token = token; await saveSimple();}
}
function geminiModel() {
  const model = $<HTMLInputElement>('gemini-model').value.trim();
  if (!/^gemini-[a-zA-Z0-9.\-]{1,100}$/.test(model)) throw new Error('ชื่อโมเดลไม่ถูกต้อง · ตัวอย่าง gemini-3.5-flash-lite');
  return model;
}
async function saveGeminiKey() {
  const field = $<HTMLInputElement>('gemini-key');
  if (field.value.trim()) {
    const status = await send('GEMINI_KEY_SAVE', {apiKey:field.value.trim()});
    field.value = ''; config.geminiRevision = status.revision;
  }
}
async function geminiAction(action: () => Promise<void>) {
  for (const id of ['gemini-test','gemini-clear','save']) $<HTMLButtonElement>(id).disabled = true;
  error(); $('gemini-result').dataset.kind = '';
  try {await action();} catch (e) {
    const message = (e as Error).message;
    const result = $('gemini-result');
    result.hidden = false; result.dataset.kind = 'error';
    result.textContent = `ไม่สำเร็จ · ${message}`;
    result.scrollIntoView({behavior:'smooth', block:'nearest'});
    error(message);
  } finally {
    for (const id of ['gemini-test','gemini-clear','save']) $<HTMLButtonElement>(id).disabled = false;
  }
}
$('gemini-test').onclick = () => geminiAction(async () => {
  const model = geminiModel();
  $('gemini-result').hidden = false;
  $('gemini-result').textContent = 'กำลังทดสอบ Gemini ด้วยข้อความตัวอย่าง…';
  await syncToken(); await saveGeminiKey(); await refreshGeminiStatus();
  const result = await send('GEMINI_TEST', {model}, 40000);
  $('gemini-result').textContent = `เชื่อมต่อ ${result.model} สำเร็จ\nต้นฉบับ: ${result.text}\nคำอ่าน: ${result.speech}`;
});
$('gemini-clear').onclick = () => geminiAction(async () => {
  await syncToken();
  config.geminiEnabled = false; config.geminiRevision = '';
  $<HTMLInputElement>('gemini-enabled').checked = false;
  $<HTMLInputElement>('gemini-key').value = '';
  await saveSimple(); await send('GEMINI_KEY_DELETE'); await refreshGeminiStatus();
  $('gemini-result').hidden = false; $('gemini-result').textContent = 'ลบ API key และปิด Gemini แล้ว';
  await health();
});
$('settings-toggle').onclick = () => {$('settings').hidden = !$('settings').hidden; if (!$('settings').hidden) $('settings').scrollIntoView({behavior:'smooth'});};
$('dictionary-add').onclick = () => {
  const wordInput = $<HTMLInputElement>('dictionary-word');
  const readingInput = $<HTMLInputElement>('dictionary-reading');
  const word = wordInput.value.trim();
  const reading = readingInput.value.trim();
  const feedback = $('dictionary-feedback');
  feedback.hidden = false;
  if (!word || !reading || /[=\r\n]/.test(word) || /[\r\n]/.test(reading)) {
    feedback.textContent = 'กรอกคำในนิยายและคำอ่านให้ครบ โดยคำในนิยายต้องไม่มีเครื่องหมาย =';
    (!word || /[=\r\n]/.test(word) ? wordInput : readingInput).focus();
    return;
  }
  const field = $<HTMLTextAreaElement>('dictionary');
  const lines = field.value.trimEnd() ? field.value.trimEnd().split('\n') : [];
  const existing = lines.findIndex(line => line.includes('=') && line.slice(0, line.indexOf('=')).trim() === word);
  if (existing >= 0) lines[existing] = `${word}=${reading}`;
  else lines.push(`${word}=${reading}`);
  field.value = lines.join('\n');
  field.scrollTop = field.scrollHeight;
  feedback.textContent = `เพิ่ม “${word}” แล้ว · กด “บันทึกและเชื่อมต่อ” เพื่อบันทึก`;
  wordInput.value = ''; readingInput.value = ''; wordInput.focus();
};
$('save').onclick = () => run(async () => {
  const dictionary: Record<string,string> = {};
  for (const line of $<HTMLTextAreaElement>('dictionary').value.split('\n').filter(s => s.trim())) {
    const index = line.indexOf('=');
    if (index < 1 || !line.slice(index+1).trim()) throw new Error('คำอ่านต้องเป็นรูปแบบ ชื่อ=คำอ่าน หนึ่งคำต่อบรรทัด');
    dictionary[line.slice(0,index).trim()] = line.slice(index+1).trim();
  }
  const enabled = $<HTMLInputElement>('gemini-enabled').checked;
  const model = geminiModel();
  await syncToken(); await saveGeminiKey();
  if (enabled) {
    const status = await send('GEMINI_STATUS');
    if (!status.key_configured) throw new Error('กรอก Gemini API key ก่อนเปิดใช้ Gemini');
    config.geminiRevision = status.revision;
  }
  config.dictionary = dictionary; config.geminiEnabled = enabled; config.geminiModel = model;
  config.geminiBatches = Number($<HTMLSelectElement>('gemini-batches').value) === 3 ? 3 : 4;
  await saveSimple(); await health();
  if ($('connection').classList.contains('connected')) {
    $('settings').hidden = true;
    window.scrollTo({top:0, behavior:'smooth'});
  }
});
for (const [id, selection] of [['load',false], ['selection',true]] as const) $(id).onclick = () => run(async () => {
  if (busy) return; busy = true;
  try {render(await send('LOAD', {selection}));} finally {busy = false;}
});
for (const action of ['previous','next','stop'] as const) $(action).onclick = () => run(async () => render(await send('CONTROL', {action})));
const clearChapterBtn = document.getElementById('clear-chapter');
if (clearChapterBtn) clearChapterBtn.onclick = () => run(async () => render(await send('CONTROL', {action: 'clear'})));
$('play').onclick = () => run(async () => render(await send('CONTROL', {action: ['playing','buffering'].includes(snapshot?.status || '') ? 'pause' : 'play'})));
$('seek').onclick = () => run(async () => render(await send('CONTROL', {action:'seek', paragraph:Number($<HTMLSelectElement>('paragraph').value)})));
$('voice').onchange = () => run(async () => {config.voice = $<HTMLSelectElement>('voice').value; await saveSimple();});
$('rate').oninput = () => {config.rate = Number($<HTMLInputElement>('rate').value); labels();};
$('rate').onchange = () => run(saveSimple);
$('volume').oninput = () => {config.volume = Number($<HTMLInputElement>('volume').value); labels();};
$('volume').onchange = () => run(saveSimple);
const bgmEnabledInput = document.getElementById('bgm-enabled') as HTMLInputElement | null;
if (bgmEnabledInput) bgmEnabledInput.onchange = () => run(async () => {config.bgmEnabled = bgmEnabledInput.checked; await saveSimple(); if (snapshot) render({...snapshot, settings: config});});
const bgmVolumeInput = document.getElementById('bgm-volume') as HTMLInputElement | null;
if (bgmVolumeInput) {
  bgmVolumeInput.oninput = () => {config.bgmVolume = Number(bgmVolumeInput.value); labels();};
  bgmVolumeInput.onchange = () => run(saveSimple);
}
$('auto-next').onchange = () => run(async () => {config.autoNext = $<HTMLInputElement>('auto-next').checked; await saveSimple();});
$('auto-scroll').onchange = () => run(async () => {config.autoScroll = $<HTMLInputElement>('auto-scroll').checked; await saveSimple();});
$('connect').onclick = () => run(health);
chrome.runtime.onMessage.addListener(message => {if (message.target === 'panel' && message.type === 'STATE') render(message.snapshot);});
void run(async () => {
  applySettings(await send('SETTINGS_GET'));
  await Promise.allSettled([
    send('GET_STATE').then(render),
    health(),
  ]);
});
