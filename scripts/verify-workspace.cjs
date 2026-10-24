// Renderer integration check: isolated storage, hidden test window, no camera or API actions.
const {
  app,
  BrowserWindow
} = require('electron');
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const root = path.join(__dirname, '..');
const output = path.join(root, '.runtime', 'ui-qa');
fs.mkdirSync(output, {
  recursive: true
});
app.setPath('userData', path.join(output, 'browser-data'));
app.disableHardwareAcceleration();
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const startedAt = new Date().toISOString();
fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify({ passed: false, status: 'running', startedAt }, null, 2));
app.whenReady().then(async () => {
  const window = new BrowserWindow({
    width: 1440,
    height: 940,
    show: false,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
      offscreen: true
    }
  });
  window.webContents.on('console-message', event => { if(event.message.includes('Tracking initialization:') || event.message.includes('Local tracker:')) console.error(event.message); });
  const requests = [];
  const externalRequests = [];
  window.webContents.session.webRequest.onBeforeRequest((details, callback) => {
    requests.push(details.url);
    const request = new URL(details.url);
    const allowed = ['file:', 'data:', 'blob:'].includes(request.protocol);
    const localCore = ['http:', 'ws:'].includes(request.protocol) && ['localhost', '127.0.0.1'].includes(request.hostname) && request.port === '8000';
    if (!allowed && !localCore) externalRequests.push(details.url);
    // This renderer-only run must stay offline, including any existing local core.
    callback({ cancel: !allowed });
  });
  try {
    await window.loadFile(path.join(root, 'dist/index.html'));
    await sleep(500);
    const evaluate = source => window.webContents.executeJavaScript(source);
    const waitFor = async predicate => { const until=Date.now()+12000; while(Date.now()<until){if(await predicate())return;await sleep(80);}throw Error('Workspace condition timed out'); };
    await evaluate(`navigator.mediaDevices.enumerateDevices=async()=>[];navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('No hardware in renderer verification','NotAllowedError');};void 0`);
    const initial = await window.webContents.executeJavaScript(`({ title: document.querySelector('h1')?.textContent,
            overflow: document.documentElement.scrollWidth > innerWidth,
            buttons: [...document.querySelectorAll('button')].filter(b => !b.textContent.trim() && !b.getAttribute('aria-label')).length })`);
    assert.equal(initial.title, 'Your space to think.');
    assert.deepEqual(await evaluate(`[...document.querySelectorAll('nav[aria-label="Main navigation"] button')].map(button=>button.getAttribute('aria-label'))`), ['Assistant','Studio','Inbox','Tasks','Connections']);
    assert.equal(initial.overflow, false);
    assert.equal(await window.webContents.executeJavaScript(`document.querySelector('.command-deck').dataset.uiContractVersion`),'1');
    assert.equal(initial.buttons, 0);
    assert.equal(await evaluate(`document.querySelector('[aria-label="Message INARA"]').disabled`), true, 'Offline assistant must not accept actions');
    assert.ok(!requests.some(url => /CadWindow-|CadStudio-|CameraPanel-|ImageStudio-|tracker-|tracking.worker-|vision_wasm|hand_landmarker/.test(url)), 'Heavy assets loaded on startup');
    fs.writeFileSync(path.join(output, 'command-desktop.png'), (await window.webContents.capturePage()).toPNG());
    await window.webContents.executeJavaScript(`document.querySelectorAll('nav button')[1].click()`);
    await sleep(350);
    fs.writeFileSync(path.join(output, 'studio-desktop.png'), (await window.webContents.capturePage()).toPNG());
    await window.webContents.executeJavaScript(`document.querySelectorAll('nav button')[0].click()`);
    await sleep(250);
    window.setContentSize(390, 844);
    await sleep(150);
    assert.equal(await window.webContents.executeJavaScript('document.documentElement.scrollWidth > innerWidth'), false);
    fs.writeFileSync(path.join(output, 'command-mobile.png'), (await window.webContents.capturePage()).toPNG());
    window.setContentSize(768, 900);
    await sleep(150);
    assert.equal(await window.webContents.executeJavaScript('document.documentElement.scrollWidth > innerWidth'), false);
    fs.writeFileSync(path.join(output, 'command-tablet.png'), (await window.webContents.capturePage()).toPNG());
    await evaluate(`document.querySelector('[aria-label="Open command palette"]').click()`);
    await waitFor(()=>evaluate(`!!document.querySelector('[aria-label="Search commands"]')`));
    await evaluate(`{const input=document.querySelector('[aria-label="Search commands"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'reminders');input.dispatchEvent(new Event('input',{bubbles:true}));}`);
    await waitFor(()=>evaluate(`document.querySelector('[role="option"] strong')?.textContent==='Reminders'`));
    await evaluate(`document.querySelector('[role="option"]').click()`);
    await sleep(300);
    assert.equal(await window.webContents.executeJavaScript(`!!document.querySelector('[role="dialog"]')`), true);
    assert.equal(await evaluate(`document.querySelector('.panel-state--offline strong')?.textContent`), 'Core offline');
    assert.ok(!requests.some(url => /CadWindow-|CadStudio-|tracker-|tracking.worker-|vision_wasm|hand_landmarker/.test(url)));
    fs.writeFileSync(path.join(output, 'reminder-panel.png'), (await window.webContents.capturePage()).toPNG());
    await window.webContents.executeJavaScript(`document.querySelector('[aria-label="Close panel"]').click()`);
    assert.equal(await window.webContents.executeJavaScript(`!!document.querySelector('[role="dialog"]')`), false);
    // Exercise keyboard command selection and all reframed interiors without running actions.
    const reframed = [
      ['settings','Preferences'],['Desktop','Desktop controls'],['Smart home','Smart home'],
      ['Print workshop','Print workshop'],['routine','Routine manager'],['devices','Connected devices'],
      ['Scene watches','Scene watches'],['Android companion','Android companion','.mobile-companion'],['Web inspector','Web inspector','.web-inspector'],
    ];
    window.setContentSize(390,900); await sleep(200);
    for (const [query,title,panel='.tool-panel'] of reframed) {
      await evaluate(`document.querySelector('[aria-label="Open command palette"]').click()`);
      await waitFor(()=>evaluate(`!!document.querySelector('[aria-label="Search commands"]')`));
      await evaluate(`{const input=document.querySelector('[aria-label="Search commands"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,${JSON.stringify(query)});input.dispatchEvent(new Event('input',{bubbles:true}));}`);
      await waitFor(()=>evaluate(`document.querySelector('[role="option"] strong')?.textContent===${JSON.stringify(title)}`));
      window.webContents.sendInputEvent({type:'keyDown',keyCode:'Enter'});window.webContents.sendInputEvent({type:'keyUp',keyCode:'Enter'});
      await waitFor(()=>evaluate(`(document.querySelector('.dialog-backdrop #feature-title')||document.querySelector('#workspace-feature-title'))?.textContent===${JSON.stringify(title)} && !!document.querySelector(${JSON.stringify(panel)})`));
      assert.equal(await evaluate(`document.querySelector('.feature-dialog').scrollWidth>document.querySelector('.feature-dialog').clientWidth`),false,`${title} overflow`);
      assert.equal(await evaluate(`document.querySelector(${JSON.stringify(panel)}).scrollWidth>document.querySelector(${JSON.stringify(panel)}).clientWidth`),false,`${title} content overflow`);
      assert.equal(await evaluate(`document.querySelector('.panel-state--offline strong')?.textContent`),'Core offline',`${title} offline state`);
      if(query==='settings') fs.writeFileSync(path.join(output,'preferences-mobile.png'),(await window.webContents.capturePage()).toPNG());
      await evaluate(`document.querySelector('[aria-label="Close panel"]').click()`);
    }
    window.setContentSize(1440,940);await sleep(400);
    window.webContents.sendInputEvent({type:'keyDown',keyCode:'K',modifiers:['control']});window.webContents.sendInputEvent({type:'keyUp',keyCode:'K',modifiers:['control']});
    await waitFor(()=>evaluate(`document.activeElement?.getAttribute('aria-label')==='Search commands'`));
    await sleep(300);
    fs.writeFileSync(path.join(output,'commands-desktop.png'),(await window.webContents.capturePage()).toPNG());
    window.webContents.sendInputEvent({type:'keyDown',keyCode:'Escape'});window.webContents.sendInputEvent({type:'keyUp',keyCode:'Escape'});
    await waitFor(()=>evaluate(`!document.querySelector('.command-palette')`));
    window.webContents.debugger.attach('1.3');
    await window.webContents.debugger.sendCommand('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
    assert.equal(await evaluate(`matchMedia('(prefers-reduced-motion: reduce)').matches`),true);
    assert.equal(await evaluate(`{const mark=document.createElement('span');mark.className='panel-progress-spinner';document.body.append(mark);const name=getComputedStyle(mark).animationName;mark.remove();name}`),'none');
    window.webContents.debugger.detach();
    for (const width of [390,768,1440,2560]) {
      window.setContentSize(width,1000); await sleep(150);
      assert.equal(await evaluate(`document.documentElement.scrollWidth>innerWidth`), false, `Overflow at ${width}`);
    }
    window.setContentSize(1440,1000);window.webContents.setZoomFactor(2);await sleep(250);
    assert.equal(await evaluate(`document.documentElement.scrollWidth>innerWidth`),false,'200% zoom overflow');
    window.webContents.setZoomFactor(1);await sleep(100);
    const normalHeading = await evaluate(`parseFloat(getComputedStyle(document.querySelector('.workspace-heading p')).fontSize)`);
    await evaluate(`document.documentElement.style.fontSize='200%'; void 0`);
    assert.ok(await evaluate(`parseFloat(getComputedStyle(document.querySelector('.workspace-heading p')).fontSize) >= ${normalHeading} * 1.9`), 'Text scaling did not enlarge the body copy');
    assert.equal(await evaluate(`document.documentElement.scrollWidth>innerWidth`),false,'200% text overflow');
    await evaluate(`document.documentElement.style.fontSize=''; void 0`);
    window.setContentSize(768,900);
    await window.webContents.executeJavaScript(`document.querySelectorAll('nav button')[1].click()`);
    await sleep(100);
    // Match synthetic stream and enumerated source; never enumerate/acquire a real camera here.
    await evaluate(`navigator.mediaDevices.enumerateDevices = async () => [{kind:'videoinput',deviceId:'qa-camera',label:'Synthetic QA camera'}]; void 0`);
    await window.webContents.executeJavaScript(`[...document.querySelectorAll('.feature-card')].find(button => button.textContent.includes('Vision studio')).click()`);
    await sleep(300);
    assert.ok(!requests.some(url => /tracker-|tracking.worker-|vision_wasm|hand_landmarker/.test(url)), 'Camera panel loaded tracking before activation');
    // Empty test stream: exercise local model initialization without acquiring a camera.
    await window.webContents.executeJavaScript(`window.qaCameraCanvas=document.createElement('canvas'); qaCameraCanvas.width=640; qaCameraCanvas.height=480; window.qaFrameTimer=setInterval(()=>qaCameraCanvas.getContext('2d').fillRect(0,0,640,480),66); navigator.mediaDevices.getUserMedia = async () => { const stream=qaCameraCanvas.captureStream(15),track=stream.getVideoTracks()[0],settings=track.getSettings.bind(track);track.getSettings=()=>({...settings(),deviceId:'qa-camera'});return stream; }; document.querySelector('.camera-controls .primary-button').click()`);
    await waitFor(()=>evaluate(`document.querySelector('.camera-panel')?.dataset.capturePhase==='active' && !document.querySelector('.vision-tracking-card .voice-button').disabled`));
    await window.webContents.executeJavaScript(`document.querySelector('.vision-tracking-card .voice-button').click()`);
    let trackerStatus = '';
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      trackerStatus = await window.webContents.executeJavaScript(`document.querySelector('.vision-tracking-status')?.textContent || ''`);
      if (trackerStatus.includes('10 FPS') || trackerStatus.includes('Tracking stopped')) break;
      await sleep(200);
    }
    if (!trackerStatus.includes('10 FPS')) console.log('Tracking end', await evaluate(`({ hidden:document.hidden, phase:document.querySelector('.camera-panel')?.dataset.capturePhase, tracking:document.querySelector('.camera-panel')?.dataset.trackingPhase, body:document.querySelector('.vision-status')?.textContent, button:document.querySelector('.vision-tracking-card .voice-button')?.textContent })`));
    assert.match(trackerStatus, /10 FPS/, 'Bundled local model did not initialize');
    await window.webContents.executeJavaScript(`document.querySelector('[aria-label="Close panel"]').click()`);
    await evaluate(`clearInterval(window.qaFrameTimer); void 0`);
    assert.deepEqual(externalRequests, [], 'All resources must be bundled locally');
    fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify({
      passed: true, startedAt,
      sizes: ['1440Ã—940', '390Ã—844', '768Ã—900'],
      initial,
      commandSearchKeyboardAndNinePanels: true, reducedMotion: true,
      widths: [390,768,1440,2560], zoom200Percent: true, rootText200Percent: true,
      heavyStartupRequests: 0,
      offlineActionsDisabled: true, rendererNetworkBlocked: true,
      bundledTrackerInitializedWithoutCamera: true
    }, null, 2));
    console.log('Workspace layout, lazy startup, accessible labels and modal checks passed.');
  } catch (error) {
    fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify({ passed: false, startedAt, error: error.stack }, null, 2));
    fs.writeFileSync(path.join(output, 'failure.png'), (await window.webContents.capturePage()).toPNG());
    console.error(error);
    process.exitCode = 1;
  } finally {
    window.destroy();
    app.exit(process.exitCode || 0);
  }
});
