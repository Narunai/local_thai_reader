import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {installReaderLauncher, sourceTab} from '../src/reader-launch';

let mock: any;
beforeEach(() => {
  mock = {
    runtime:{getManifest:()=>({side_panel:{default_path:'dist/panel.html'}}),
      getURL:(p:string)=>`chrome-extension://test/${p}`,
      onInstalled:{addListener:vi.fn()}, onStartup:{addListener:vi.fn()}},
    action:{onClicked:{addListener:vi.fn()},setPopup:vi.fn().mockResolvedValue(undefined),
      setBadgeText:vi.fn().mockResolvedValue(undefined),setTitle:vi.fn().mockResolvedValue(undefined)},
    sidePanel:{open:vi.fn().mockResolvedValue(undefined), setOptions:vi.fn().mockResolvedValue(undefined),
      setPanelBehavior:vi.fn().mockResolvedValue(undefined)},
    tabs:{create:vi.fn().mockResolvedValue({}),get:vi.fn().mockResolvedValue({id:17}),
      query:vi.fn().mockResolvedValue([{id:20}])},
  };
  vi.stubGlobal('chrome',mock);
  vi.spyOn(console,'warn').mockImplementation(()=>{});
});
afterEach(()=>{vi.unstubAllGlobals();vi.restoreAllMocks();});

it('restores native toolbar behavior and clears the old popup on every lifecycle event',async()=>{
  installReaderLauncher();
  await vi.waitFor(()=>expect(mock.sidePanel.setPanelBehavior).toHaveBeenCalledWith({openPanelOnActionClick:true}));
  expect(mock.action.onClicked.addListener).toHaveBeenCalledTimes(1);
  expect(mock.action.setPopup).toHaveBeenCalledWith({popup:''});
  expect(mock.sidePanel.setOptions).toHaveBeenCalledWith({path:'dist/panel.html',enabled:true});
  mock.runtime.onStartup.addListener.mock.calls[0][0]();
  mock.runtime.onInstalled.addListener.mock.calls[0][0]();
  expect(mock.sidePanel.setOptions).toHaveBeenCalledTimes(3);
});

it('opens from the click event immediately even before native behavior is restored',()=>{
  installReaderLauncher();
  mock.action.onClicked.addListener.mock.calls[0][0]({id:17,windowId:4});
  expect(mock.sidePanel.open).toHaveBeenCalledWith({windowId:4});
  expect(mock.tabs.query).not.toHaveBeenCalled();
  expect(mock.tabs.create).not.toHaveBeenCalled();
});

it('uses the active book in the normal side panel and reports a closed fallback source',async()=>{
  expect(await sourceTab({url:'chrome-extension://test/panel.html'})).toEqual({id:20});
  mock.tabs.get.mockRejectedValue(new Error('No tab'));
  await expect(sourceTab({url:'chrome-extension://test/panel.html?sourceTab=17'})).rejects.toThrow('ต้นฉบับถูกปิด');
});

it('finds the most recently used website when opened directly or from extension options',async()=>{
  mock.tabs.query.mockResolvedValueOnce([{id:20,url:'chrome-extension://test/panel.html'}])
    .mockResolvedValueOnce([{id:11,url:'https://og-thai.blogspot.com/old',lastAccessed:1},
      {id:17,url:'https://og-thai.blogspot.com/current',lastAccessed:10},
      {id:20,url:'chrome-extension://test/panel.html',lastAccessed:99}]);
  expect((await sourceTab({url:'chrome-extension://test/panel.html'})).id).toBe(17);
});

it('asks for a book when direct reader entry has no readable website',async()=>{
  mock.tabs.query.mockResolvedValue([{id:20,url:'chrome-extension://test/panel.html'}]);
  await expect(sourceTab({url:'chrome-extension://test/panel.html'})).rejects.toThrow('เปิดหน้านิยาย');
});
