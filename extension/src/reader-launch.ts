export function readerPath(): string {
  return chrome.runtime.getManifest().side_panel?.default_path || 'panel.html';
}

export function installReaderLauncher(): void {
  // Register synchronously so a toolbar click can wake a stopped worker even
  // if the saved native behavior is still disabled after a failed startup.
  chrome.action.onClicked.addListener(tab => {
    try {
      void chrome.sidePanel.open({windowId:tab.windowId!}).catch(report);
    } catch (error) { report(error); }
  });
  function report(error: unknown) {
    console.error('ตั้งค่าการเปิดแผงเล่านิยายไม่สำเร็จ', error);
    void chrome.action.setBadgeText({text:'!'});
    void chrome.action.setTitle({title:`เปิดแผงไม่สำเร็จ: ${(error as Error).message}`});
  }
  const configure = async () => {
    try {
      // Chrome owns the toolbar action: it works even when the worker is asleep.
      // Clear the old popup override and restore options when updating/reloading.
      await Promise.all([
        chrome.action.setPopup({popup:''}),
        chrome.sidePanel.setOptions({path:readerPath(), enabled:true}),
      ]);
      await chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:true});
      await chrome.action.setBadgeText({text:''});
      await chrome.action.setTitle({title:'เปิดเล่านิยาย'});
    } catch (error) {
      report(error);
    }
  };
  chrome.runtime.onInstalled.addListener(configure);
  chrome.runtime.onStartup.addListener(configure);
  void configure();
}

export async function sourceTab(sender: chrome.runtime.MessageSender): Promise<chrome.tabs.Tab> {
  const source = sender.url ? new URL(sender.url).searchParams.get('sourceTab') : null;
  if (source && /^\d+$/.test(source)) {
    try { return await chrome.tabs.get(Number(source)); }
    catch { throw new Error('แท็บนิยายต้นฉบับถูกปิด กรุณาเปิดนิยายแล้วคลิกไอคอน Extension อีกครั้ง'); }
  }
  const [tab] = await chrome.tabs.query({active:true, currentWindow:true});
  if (!tab) throw new Error('ไม่พบแท็บที่เปิดอยู่');
  if (tab.url?.startsWith(chrome.runtime.getURL(''))) {
    // Options/direct-entry pages are tabs themselves. Find the most recently
    // used readable website instead of trying to inject into our own controls.
    const tabs = await chrome.tabs.query({currentWindow:true});
    const book = tabs.filter(t=>t.url && /^https?:/.test(t.url))
      .sort((a,b)=>(b.lastAccessed||0)-(a.lastAccessed||0))[0];
    if (!book) throw new Error('เปิดหน้านิยายในหน้าต่างนี้ก่อน แล้วกลับมากด “อ่านบทนี้”');
    return book;
  }
  return tab;
}
