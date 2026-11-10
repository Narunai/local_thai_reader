// Verify every supported unpacked directory in a fresh, isolated Chromium profile.
import assert from 'node:assert/strict';
import {mkdir, mkdtemp, readFile, stat, writeFile} from 'node:fs/promises';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
const cache = process.env.NOVEL_CACHE_HOME || 'D:/AI_Cache';
process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(cache, 'playwright');
process.env.TEMP = path.join(cache, 'temp');
process.env.TMP = process.env.TEMP;
const profiles = path.join(cache, 'browser-profiles');
await mkdir(profiles, {recursive:true});
const {chromium} = await import('playwright');
const report = {status:'passed', layouts:[]};

for (const layout of ['dist', 'public', '.']) {
  const folder = path.resolve(root, layout);
  const manifest = JSON.parse(await readFile(path.join(folder, 'manifest.json'), 'utf8'));
  for (const relative of [manifest.background.service_worker, manifest.side_panel.default_path]) {
    const target = path.resolve(folder, relative);
    const within = path.relative(folder, target);
    assert(!within.startsWith('..') && !path.isAbsolute(within), 'Manifest path leaves extension directory');
    assert((await stat(target)).isFile(), `Missing manifest target: ${relative}`);
  }
  const profile = await mkdtemp(path.join(profiles, 'manifest-check-'));
  const context = await chromium.launchPersistentContext(profile, {
    channel:'chromium', headless:true,
    args:[`--disable-extensions-except=${folder}`, `--load-extension=${folder}`],
  });
  try {
    const worker = context.serviceWorkers()[0] || await context.waitForEvent('serviceworker', {timeout:15000});
    const id = new URL(worker.url()).host;
    assert(worker.url().endsWith('/' + manifest.background.service_worker));
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(`chrome-extension://${id}/${manifest.side_panel.default_path}`);
    await page.locator('#settings-toggle').waitFor();
    const options = await worker.evaluate(() => chrome.sidePanel.getOptions({}));
    assert.equal(options.enabled, true);
    assert.equal(options.path, manifest.side_panel.default_path);
    assert.equal(manifest.action.default_popup, undefined);
    assert.equal(manifest.options_page, undefined);
    const behavior = await worker.evaluate(() => chrome.sidePanel.getPanelBehavior());
    assert.equal(behavior.openPanelOnActionClick, true);
    const result = await page.evaluate(() => chrome.runtime.sendMessage({target:'worker', type:'GET_STATE'}));
    assert.equal(result?.ok, true, result?.error || 'Worker did not respond');
    assert.equal(result.value.status, 'idle');
    const contexts = await worker.evaluate(() => chrome.runtime.getContexts({contextTypes:[chrome.runtime.ContextType.OFFSCREEN_DOCUMENT]}));
    const prefix = path.posix.dirname(manifest.side_panel.default_path);
    const offscreen = prefix === '.' ? 'offscreen.html' : `${prefix}/offscreen.html`;
    assert(contexts.some(item => item.documentUrl === `chrome-extension://${id}/${offscreen}`));
    assert.deepEqual(errors, []);
    report.layouts.push({folder:layout, version:manifest.version, native_toolbar_enabled:true, service_worker:manifest.background.service_worker,
      panel:manifest.side_panel.default_path, offscreen, status:'passed'});
    console.log(`PASS: extension/${layout} registers worker, enables native toolbar side panel, and creates audio document`);
  } finally {
    await context.close();
  }
}
await mkdir(path.join(root, 'reports'), {recursive:true});
await writeFile(path.join(root, 'reports/manifest-e2e.json'), JSON.stringify(report,null,2));
