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
  window.webContents.on('console-message', (_, level, message) => { if(message.includes('Tracking initialization:')) console.error(message); });
  const requests = [];
  window.webContents.session.webRequest.onBeforeRequest((details, callback) => {
    requests.push(details.url);
    callback({});
  });
  try {
    await window.loadFile(path.join(root, 'dist/index.html'));
    await sleep(500);
    const initial = await window.webContents.executeJavaScript(`({ title: document.querySelector('h1')?.textContent,
            overflow: document.documentElement.scrollWidth > innerWidth,
            buttons: [...document.querySelectorAll('button')].filter(b => !b.textContent.trim() && !b.getAttribute('aria-label')).length })`);
    assert.match(initial.title, /Ready when/);
    assert.equal(initial.overflow, false);
    assert.equal(initial.buttons, 0);
    assert.ok(!requests.some(url => /CadWindow-|tracker-|vision_wasm|hand_landmarker/.test(url)), 'Heavy assets loaded on startup');
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
    await window.webContents.executeJavaScript(`document.querySelector('.reminders-card .text-button').click()`);
    await sleep(300);
    assert.equal(await window.webContents.executeJavaScript(`!!document.querySelector('[role="dialog"]')`), true);
    assert.ok(!requests.some(url => /CadWindow-|tracker-|vision_wasm|hand_landmarker/.test(url)));
    fs.writeFileSync(path.join(output, 'reminder-panel.png'), (await window.webContents.capturePage()).toPNG());
    await window.webContents.executeJavaScript(`document.querySelector('[aria-label="Close panel"]').click()`);
    assert.equal(await window.webContents.executeJavaScript(`!!document.querySelector('[role="dialog"]')`), false);
    await window.webContents.executeJavaScript(`document.querySelectorAll('nav button')[1].click()`);
    await sleep(100);
    await window.webContents.executeJavaScript(`[...document.querySelectorAll('.feature-card')].find(button => button.textContent.includes('Vision studio')).click()`);
    await sleep(300);
    assert.ok(!requests.some(url => /tracker-|vision_wasm|hand_landmarker/.test(url)), 'Camera panel loaded tracking before activation');
    // Empty test stream: exercise local model initialization without acquiring a camera.
    await window.webContents.executeJavaScript(`navigator.mediaDevices.getUserMedia = async () => new MediaStream(); document.querySelector('.camera-controls .primary-button').click()`);
    await sleep(200);
    await window.webContents.executeJavaScript(`document.querySelector('.camera-controls .voice-button').click()`);
    let trackerStatus = '';
    const deadline = Date.now() + 20000;
    while (Date.now() < deadline) {
      trackerStatus = await window.webContents.executeJavaScript(`document.querySelector('.camera-details')?.textContent || ''`);
      if (trackerStatus.includes('10 FPS') || trackerStatus.includes('could not load')) break;
      await sleep(200);
    }
    assert.match(trackerStatus, /10 FPS/, 'Bundled local model did not initialize');
    await window.webContents.executeJavaScript(`document.querySelector('[aria-label="Close panel"]').click()`);
    fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify({
      sizes: ['1440Ã—940', '390Ã—844', '768Ã—900'],
      initial,
      heavyStartupRequests: 0,
      bundledTrackerInitializedWithoutCamera: true
    }, null, 2));
    console.log('Workspace layout, lazy startup, accessible labels and modal checks passed.');
  } catch (error) {
    console.error(error);
    process.exitCode = 1;
  } finally {
    window.destroy();
    app.exit(process.exitCode || 0);
  }
});
