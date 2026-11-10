import { installReaderLauncher } from './reader-launch';

declare function importScripts(...urls: string[]): void;

// Register the launcher before loading the reader engine. A failure in the
// engine must not leave the toolbar without a registered click/startup event.
installReaderLauncher();
try {
  importScripts('reader-runtime.js');
} catch (error) {
  const message = `เริ่มระบบอ่านเสียงไม่สำเร็จ: ${(error as Error).message}`;
  console.error(message, error);
  chrome.runtime.onMessage.addListener((request, _sender, respond) => {
    if (request.target === 'worker') respond({ok:false, error:message});
  });
}
