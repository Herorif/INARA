// Actual hidden native shell. The paired Python harness owns synthetic local fixtures.
const { BrowserWindow } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const pipe = fs.readFileSync(0, 'utf8');
const bootstrap = JSON.parse(pipe);
const read = fs.readFileSync;
fs.readFileSync = function (file, ...args) {
  return file === 0 ? pipe : read.call(this, file, ...args);
};
const output = bootstrap.qaOutput;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const until = async (predicate, label, timeout = 25000) => {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await sleep(80);
  }
  throw Error(`Command workspace condition timed out: ${label}`);
};
const load = BrowserWindow.prototype.loadFile;
BrowserWindow.prototype.loadFile = async function (...args) {
  const window = this;
  const requests = [], deniedRequests = [], rendererErrors = [];
  let mediaPermissions = 0;
  window.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => {
    mediaPermissions++;
    callback(false);
  });
  // Record from before the first document load, including eager preload dependencies.
  window.webContents.session.webRequest.onBeforeRequest((details, callback) => {
    requests.push(details.url);
    const url = new URL(details.url);
    const allowed = ['file:', 'data:', 'blob:'].includes(url.protocol) ||
      (['http:', 'ws:'].includes(url.protocol) && ['127.0.0.1', 'localhost'].includes(url.hostname) && url.port === '8000');
    if (!allowed) deniedRequests.push(details.url);
    callback({ cancel: !allowed });
  });
  window.webContents.on('console-message', event => {
    if (event.level === 'error' && !event.message.includes('net::ERR_')) rendererErrors.push(event.message);
  });
  await load.apply(window, args);
  const evaluate = source => window.webContents.executeJavaScript(source);
  const result = {};
  const screenshot = async name => {
    await sleep(150);
    fs.writeFileSync(path.join(output, name), (await window.webContents.capturePage()).toPNG());
  };
  const key = (keyCode, modifiers = []) => {
    window.webContents.sendInputEvent({ type: 'keyDown', keyCode, modifiers });
    window.webContents.sendInputEvent({ type: 'keyUp', keyCode, modifiers });
  };
  const click = selector => evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
  const command = async (query, title) => {
    key('K', ['control']);
    await until(() => evaluate(`document.activeElement?.getAttribute('aria-label') === 'Search commands'`), 'command search focus');
    await evaluate(`(() => {
      const field = document.querySelector('[aria-label="Search commands"]');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(field, ${JSON.stringify(query)});
      field.dispatchEvent(new Event('input', { bubbles: true }));
    })()`);
    await until(() => evaluate(`document.querySelector('[role="option"] strong')?.textContent === ${JSON.stringify(title)}`), `${title} search result`);
    key('Enter');
    await until(() => evaluate(`(document.querySelector('.dialog-backdrop #feature-title') || document.querySelector('#workspace-feature-title'))?.textContent === ${JSON.stringify(title)}`), `${title} opened`);
  };
  const noOverflow = async label => {
    const overflow = await evaluate(`(() => {
      const selectors = ['html', '.navigation', '.workspace', '.feature-workspace', '.connections-readiness', '.image-studio', '.task-queue', '.call-lab'];
      return selectors.flatMap(selector => [...document.querySelectorAll(selector)])
        .filter(element => element.getClientRects().length && element.scrollWidth > element.clientWidth + 1)
        .map(element => ({ element: element.className || element.tagName, width: element.clientWidth, scrollWidth: element.scrollWidth }));
    })()`);
    assert.deepEqual(overflow, [], `${label}: ${JSON.stringify(overflow)}`);
  };
  try {
    await until(() => evaluate(`document.querySelector('.pulse-status strong')?.textContent === 'At your service'`), 'core online');
    await evaluate(`window.commandQA = { mediaCalls: 0, enumerateCalls: 0 };
      navigator.mediaDevices.enumerateDevices = async () => { commandQA.enumerateCalls++; return []; };
      navigator.mediaDevices.getUserMedia = async () => { commandQA.mediaCalls++; throw new DOMException('No media in shell verification', 'NotAllowedError'); }; void 0`);
    assert.deepEqual(await evaluate(`[...document.querySelectorAll('nav[aria-label="Main navigation"] button')].map(button => button.getAttribute('aria-label'))`),
      ['Assistant', 'Studio', 'Inbox', 'Tasks', 'Connections']);
    assert.equal(await evaluate(`document.querySelector('.command-deck').dataset.uiContractVersion`), '1');
    assert.equal(await evaluate(`document.querySelector('.workspace-heading h1').textContent`), 'Your space to think.');
    assert.equal(await evaluate(`[...document.querySelectorAll('button')].filter(button => !button.textContent.trim() && !button.getAttribute('aria-label')).length`), 0);
    const heavyStartup = requests.filter(url => /\/(?:CadWindow|CadStudio|CameraPanel|ImageStudio|tracking\.worker|vision_wasm)|hand_landmarker/.test(url));
    assert.deepEqual(heavyStartup, [], 'Heavy tools must remain absent before explicit selection');
    await noOverflow('Assistant desktop');
    await screenshot('command-assistant-initial-1440.png');

    // The command palette must remain usable while a long-running tool owns the canvas.
    await command('Connections readiness', 'Connections readiness');
    await until(() => evaluate(`document.querySelectorAll('.connection-state--unverified').length === 2`), 'synthetic readiness');
    assert.equal(await evaluate(`!!document.querySelector('.feature-workspace') && !document.querySelector('.feature-workspace[aria-modal="true"]') && !document.querySelector('.dialog-backdrop')`), true);
    assert.equal(await evaluate(`document.querySelector('.connections-readiness').textContent.includes('10.0.0.2') || document.querySelector('.connections-readiness').textContent.includes('printer.test')`), false);
    await evaluate(`(() => {
      const nodes = [...document.querySelector('.feature-workspace').querySelectorAll('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),[tabindex="0"]')]
        .filter(element => element.getClientRects().length);
      nodes.at(-1).focus();
    })()`);
    key('Tab');
    await sleep(100);
    assert.equal(await evaluate(`!!document.activeElement.closest('.feature-workspace')`), false, 'Tab must leave the docked canvas');
    await command('Image atelier', 'Image atelier');
    await until(() => evaluate(`document.querySelector('.image-availability p')?.textContent.includes('deferred')`), 'image setup state');
    assert.equal(await evaluate(`document.querySelector('.image-generate').disabled`), true);
    assert.equal(await evaluate(`!!document.querySelector('.image-canvas img')`), false);
    assert.ok(requests.some(url => /ImageStudio-.*\.js/.test(url)), 'Image workspace must load when selected');
    assert.equal(requests.some(url => /\/(?:CadWindow|CadStudio|CameraPanel|tracking\.worker|vision_wasm)|hand_landmarker/.test(url)), false);
    await screenshot('command-image-setup-1440.png');
    await noOverflow('Docked image desktop');
    await evaluate(`window.commandQA.imageNode = document.querySelector('.image-studio');
      (() => { const field = document.querySelector('.image-director textarea');
        Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(field, 'A synthetic retained image direction');
        field.dispatchEvent(new Event('input', { bubbles: true })); })()`);
    await command('settings', 'Preferences');
    assert.equal(await evaluate(`document.querySelector('.dialog-backdrop .feature-dialog')?.getAttribute('aria-modal')`), 'true');
    assert.equal(await evaluate(`document.querySelector('.image-studio') === commandQA.imageNode`), true, 'Opening Preferences must preserve the docked viewer');
    key('Escape');
    await until(() => evaluate(`!document.querySelector('.dialog-backdrop')`), 'Preferences over dock dismissal');
    assert.equal(await evaluate(`document.querySelector('.image-studio') === commandQA.imageNode && document.querySelector('.image-director textarea').value === 'A synthetic retained image direction'`), true);
    key('Escape');
    await sleep(80);
    assert.equal(await evaluate(`document.querySelector('.image-studio') === commandQA.imageNode`), true, 'Escape must not dismiss the docked workspace');

    await evaluate(`document.querySelector('.feature-workspace [aria-label="Close panel"]').focus()`);
    await click('.feature-workspace [aria-label="Close panel"]');
    await until(() => evaluate(`!document.querySelector('.feature-workspace') && document.activeElement !== document.body && document.activeElement?.isConnected`), 'Focus restored after closing dock');
    await click('nav [aria-label="Connections"]');
    await until(() => evaluate(`document.querySelectorAll('.connection-state--unverified').length === 2`), 'Connections navigation');
    fs.writeFileSync(path.join(output, 'readiness-error-requested.json'), '{}');
    await click('[aria-label="Refresh connection readiness"]');
    await until(() => evaluate(`document.querySelector('.connections-readiness__error')?.textContent.includes('could not be inspected')`), 'readiness error');
    await screenshot('command-connections-recovery.png');
    await click('[aria-label="Refresh connection readiness"]');
    await until(() => evaluate(`!document.querySelector('.connections-readiness__error') && !document.querySelector('[aria-label="Refresh connection readiness"]').disabled`), 'readiness recovery');

    for (const page of ['Assistant', 'Studio', 'Inbox', 'Tasks', 'Connections']) {
      await click(`nav [aria-label="${page}"]`);
      await until(() => evaluate(`document.querySelector('nav [aria-current="page"]')?.getAttribute('aria-label') === ${JSON.stringify(page)}`), `${page} navigation`);
      if (page === 'Tasks') await until(() => evaluate(`!!document.querySelector('.task-queue__list')`), 'Tasks content');
      if (page === 'Inbox') {
        await until(() => evaluate(`!!document.querySelector('.inbox-empty')`), 'Empty private inbox');
        assert.equal(await evaluate(`document.querySelector('.inbox-stream-footer').textContent.includes('Replies and AI processing are off')`), true);
        assert.equal(await evaluate(`!!document.querySelector('.notification-policy') || !!document.querySelector('.mobile-invitation')`), false);
      }
      for (const width of [390, 768, 1440, 2560]) {
        window.setContentSize(width, 1000);
        await sleep(120);
        await noOverflow(`${page} at ${width}`);
        if (width === 390 || width === 1440) await screenshot(`command-${page.toLowerCase()}-${width}.png`);
      }
    }
    result.navigation_widths = [390, 768, 1440, 2560];
    result.navigation_pages = ['Assistant', 'Studio', 'Inbox', 'Tasks', 'Connections'];
    window.setContentSize(1440, 1000);
    await click('nav [aria-label="Assistant"]');
    const inspectorControl = '[aria-controls="workspace-inspector"]';
    const inspectorExpanded = await evaluate(`document.querySelector(${JSON.stringify(inspectorControl)}).getAttribute('aria-expanded')`);
    await click(inspectorControl);
    await until(() => evaluate(`document.querySelector(${JSON.stringify(inspectorControl)}).getAttribute('aria-expanded') !== ${JSON.stringify(inspectorExpanded)}`), 'inspector toggled');
    assert.equal(await evaluate(`!!document.querySelector('#workspace-inspector')`), inspectorExpanded === 'false');
    if (inspectorExpanded === 'false') await screenshot('command-context-1440.png');
    await click(inspectorControl);
    await until(() => evaluate(`document.querySelector(${JSON.stringify(inspectorControl)}).getAttribute('aria-expanded') === ${JSON.stringify(inspectorExpanded)}`), 'inspector restored');
    const trayControl = '[aria-controls="workspace-activity-tray"]';
    const trayExpanded = await evaluate(`document.querySelector(${JSON.stringify(trayControl)}).getAttribute('aria-expanded')`);
    await click(trayControl);
    await until(() => evaluate(`document.querySelector(${JSON.stringify(trayControl)}).getAttribute('aria-expanded') !== ${JSON.stringify(trayExpanded)}`), 'activity tray toggled');
    await click(trayControl);

    // Only genuine modal surfaces retain focus wrapping and Escape dismissal.
    await command('settings', 'Preferences');
    assert.equal(await evaluate(`document.querySelector('.feature-dialog')?.getAttribute('aria-modal')`), 'true');
    const modalEnds = await evaluate(`(() => {
      const nodes = [...document.querySelector('.feature-dialog').querySelectorAll('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),[tabindex="0"]')]
        .filter(element => element.getClientRects().length);
      nodes[0].focus(); return nodes.length;
    })()`);
    assert.ok(modalEnds > 1);
    key('Tab', ['shift']);
    await sleep(80);
    assert.equal(await evaluate(`(() => {
      const nodes = [...document.querySelector('.feature-dialog').querySelectorAll('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),[tabindex="0"]')].filter(element => element.getClientRects().length);
      return document.activeElement === nodes.at(-1);
    })()`), true, 'Preferences must keep modal focus wrapping');
    key('Escape');
    await until(() => evaluate(`!document.querySelector('.feature-dialog')`), 'Preferences dismissal');

    await command('Call bridge lab', 'Call bridge lab');
    const checkButton = '.call-lab__actions .primary-button';
    await until(() => evaluate(`!!document.querySelector('${checkButton}') && !document.querySelector('${checkButton}').disabled`), 'call lab readiness');
    assert.equal(await evaluate(`document.querySelector('.call-lab__badge').textContent.includes('Live answering off')`), true);
    await screenshot('command-call-lab-1440.png');
    await click(checkButton);
    await until(() => evaluate(`!!document.querySelector('.call-lab__state.is-running')`), 'check running');
    await click('.call-lab__actions button:not(.primary-button)');
    await until(() => evaluate(`!document.querySelector('.call-lab__state.is-running') && !document.querySelector('${checkButton}').disabled`), 'check stopped');
    await click(checkButton);
    await until(() => evaluate(`!!document.querySelector('.call-lab__state.is-completed') && !document.querySelector('${checkButton}').disabled`), 'check completed');
    await evaluate(`document.querySelector('.call-lab__state.is-completed').closest('article').querySelector('button').click()`);
    await until(() => evaluate(`!!document.querySelector('.call-lab__transcript .call-lab__segment')`), 'protected synthetic transcript');
    await evaluate(`document.querySelector('.call-lab__transcript').scrollIntoView({block:'end'})`);
    await screenshot('command-call-lab-record-1440.png');
    window.setContentSize(390, 1000);
    await sleep(150);
    await noOverflow('Call lab at 390');
    await evaluate(`document.querySelector('.call-lab__transcript').scrollIntoView({block:'end'})`);
    await screenshot('command-call-lab-record-390.png');
    await evaluate(`document.querySelector('.call-lab__hero').scrollIntoView({block:'start'})`);
    await screenshot('command-call-lab-390.png');
    window.setContentSize(1440, 1000);
    await click(checkButton);
    await until(() => evaluate(`!!document.querySelector('.call-lab__state.is-running')`), 'close check running');
    await click('.feature-workspace [aria-label="Close panel"]');
    await command('Call bridge lab', 'Call bridge lab');
    await until(() => evaluate(`!document.querySelector('.call-lab__state.is-running') && !document.querySelector('${checkButton}').disabled`), 'panel close stopped check');
    await click('.feature-workspace [aria-label="Close panel"]');
    await click('nav [aria-label="Assistant"]');
    result.call_lab_readiness = true;
    result.isolated_check_stop_and_record = true;
    result.panel_close_stops_check = true;

    window.webContents.debugger.attach('1.3');
    await window.webContents.debugger.sendCommand('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
    assert.equal(await evaluate(`matchMedia('(prefers-reduced-motion: reduce)').matches`), true);
    assert.equal(await evaluate(`(() => { const element = document.createElement('span'); element.className = 'panel-progress-spinner'; document.body.append(element); const animation = getComputedStyle(element).animationName; element.remove(); return animation; })()`), 'none');
    window.webContents.debugger.detach();
    window.webContents.setZoomFactor(2);
    await sleep(180);
    await noOverflow('200% zoom');
    await screenshot('command-zoom-200.png');
    window.webContents.setZoomFactor(1);
    const textSize = await evaluate(`parseFloat(getComputedStyle(document.querySelector('.chat-welcome p')).fontSize)`);
    await evaluate(`document.documentElement.style.fontSize = '200%'; void 0`);
    assert.ok(await evaluate(`parseFloat(getComputedStyle(document.querySelector('.chat-welcome p')).fontSize) >= ${textSize} * 1.9`), 'Root text scaling must enlarge body copy');
    await noOverflow('200% text scaling');
    assert.equal(await evaluate(`document.querySelector('.brand-sub').getBoundingClientRect().bottom <= document.querySelector('.titlebar').getBoundingClientRect().bottom + 1`), true, 'Scaled brand copy must fit within the titlebar');
    await screenshot('command-text-200.png');
    await evaluate(`document.documentElement.style.fontSize = ''; void 0`);
    assert.equal(await evaluate(`commandQA.mediaCalls`), 0);
    assert.equal(mediaPermissions, 0);
    assert.deepEqual(deniedRequests, [], 'No external network requests are permitted in shell verification');
    assert.deepEqual(rendererErrors, [], 'Renderer errors');
    result.passed = true;
    result.docked_keyboard_navigation = true;
    result.close_dock_restores_keyboard_focus = true;
    result.modal_focus_and_escape = true;
    result.preferences_preserve_docked_viewer_and_draft = true;
    result.inspector_and_activity_toggle = true;
    result.setup_error_and_refresh_recovery = true;
    result.heavy_startup_requests = 0;
    result.zoom_200_percent = true;
    result.text_200_percent = true;
    result.reduced_motion = true;
    result.camera_and_microphone_requests = 0;
    result.external_network_requests = 0;
  } catch (error) {
    result.passed = false;
    result.error = error.stack;
    result.panel_text = await evaluate(`document.querySelector('.call-lab')?.textContent || ''`);
    result.renderer_errors = rendererErrors;
    await screenshot('command-failure.png');
  }
  fs.writeFileSync(path.join(output, 'ui-verification.json'), JSON.stringify(result, null, 2));
  await evaluate('window.electronAPI.close()');
};
require('../electron/native-main.cjs');
