// Real hidden workspace integration. Only isolated test projects/downloads are touched.
const {
  BrowserWindow
} = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const {
  pathToFileURL
} = require('node:url');
const assert = require('node:assert/strict');
const pipe = fs.readFileSync(0, 'utf8'),
  bootstrap = JSON.parse(pipe);
const read = fs.readFileSync;
fs.readFileSync = function (file, ...args) {
  return file === 0 ? pipe : read.call(this, file, ...args);
};
const output = bootstrap.qaOutput;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const until = async (predicate, timeout = 15000) => {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (await predicate()) return;
    await sleep(100);
  }
  throw Error('CAD workspace condition timed out');
};
const load = BrowserWindow.prototype.loadFile;
BrowserWindow.prototype.loadFile = async function (...args) {
  const window = this;
  await load.apply(window, args);
  const evaluate = source => window.webContents.executeJavaScript(source);
  const result = {};
  window.webContents.on("console-message", (_, level, message) => { if (level === 3) console.error("QA renderer:", message); });
  try {
    const requests = [];
    window.webContents.session.webRequest.onBeforeRequest((details, callback) => {
      requests.push(details.url);
      callback({});
    });
    const downloads = [];
    window.webContents.session.on('will-download', (_, item) => {
      const destination = path.join(output, 'exports', path.basename(item.getFilename()));
      fs.mkdirSync(path.dirname(destination), {
        recursive: true
      });
      item.setSavePath(destination);
      item.once('done', (_, state) => {
        if (state === 'completed') downloads.push(destination);
      });
    });
    await until(() => evaluate(`document.querySelector('.pulse-status strong')?.textContent === 'At your service'`));
    await evaluate(`document.querySelectorAll('nav button')[1].click()`);
    await until(() => evaluate(`[...document.querySelectorAll('.feature-card')].some(button => button.textContent.includes('3D studio'))`));
    await evaluate(`[...document.querySelectorAll('.feature-card')].find(button => button.textContent.includes('3D studio')).click()`);
    await until(() => evaluate(`!!document.querySelector('.cad-studio')`));
    for (const [shape, index] of [['box', 0], ['bracket', 1], ['enclosure', 2]]) {
      await evaluate(`document.querySelectorAll('.cad-shapes button')[${index}].click()`);
      await until(() => evaluate(`document.querySelectorAll('.cad-shapes button')[${index}].getAttribute('aria-pressed') === 'true'`));
      await evaluate(`document.querySelector('.cad-build').click()`);
      const volume = {
        box: '144.00',
        bracket: '20.88',
        enclosure: '36.11'
      }[shape];
      await until(() => evaluate(`document.querySelector('.cad-status strong')?.textContent === 'Ready to explore' && document.querySelector('.cad-history-list button.selected small')?.textContent.startsWith('${shape}') && document.querySelector('.cad-stats')?.textContent.includes('${volume}')`));
      await until(() => evaluate(`document.querySelector('.cad-viewport')?.dataset.modelLoaded === 'true'`));
      assert.equal(await evaluate(`!!document.querySelector('.cad-viewport canvas')`), true);
      result[`${shape}_rendered`] = true;
      if (shape !== 'enclosure') await sleep(100);
    }
    await sleep(400);
    fs.writeFileSync(path.join(output, 'cad-desktop.png'), (await window.webContents.capturePage()).toPNG());
    for (let index = 0; index < 3; index++) {
      await evaluate(`document.querySelectorAll('.cad-export button')[${index}].click()`);
      await until(() => downloads.length === index + 1);
      await until(() => evaluate(`!document.querySelector('.cad-export button').disabled`));
    }
    assert.equal(downloads.filter(file => file.endsWith('.stl')).length, 1);
    assert.equal(downloads.filter(file => file.endsWith('.glb')).length, 1);
    assert.equal(downloads.filter(file => file.endsWith('.json')).length, 1);
    const {
      GLTFLoader
    } = await import(pathToFileURL(path.join(__dirname, '../node_modules/three/examples/jsm/loaders/GLTFLoader.js')).href);
    const binary = fs.readFileSync(downloads.find(file => file.endsWith('.glb')));
    const gltf = await new Promise((resolve, reject) => new GLTFLoader().parse(binary.buffer.slice(binary.byteOffset, binary.byteOffset + binary.byteLength), '', resolve, reject));
    assert.ok(gltf.scene.children[0].geometry.attributes.position.count > 0);
    result.glb_imported_with_three = true;
    result.download_formats = ['stl', 'glb', 'json'];
    await evaluate(`document.querySelector('.cad-preview-top button').click()`);
    assert.match(await evaluate(`document.querySelector('.cad-view-label').textContent`), /WIREFRAME/);
    window.setContentSize(390, 844);
    await sleep(200);
    assert.equal(await evaluate(`document.documentElement.scrollWidth > innerWidth || document.querySelector('.cad-studio').scrollWidth > document.querySelector('.cad-studio').clientWidth`), false);
    fs.writeFileSync(path.join(output, 'cad-mobile.png'), (await window.webContents.capturePage()).toPNG());
    await evaluate(`document.querySelector('.cad-workbench').scrollIntoView({ block: 'start' })`);
    await sleep(200);
    fs.writeFileSync(path.join(output, 'cad-mobile-preview.png'), (await window.webContents.capturePage()).toPNG());
    window.setContentSize(768, 900);
    await sleep(200);
    assert.equal(await evaluate(`document.documentElement.scrollWidth > innerWidth || document.querySelector('.cad-studio').scrollWidth > document.querySelector('.cad-studio').clientWidth`), false);
    result.responsive_widths = [1440, 390, 768];
    assert.equal(requests.some(url => /^https?:\/\//.test(url) && !/^http:\/\/(localhost|127\.0\.0\.1):8000/.test(url)), false);
    result.external_asset_requests = 0;
    await evaluate(`document.querySelector('[aria-label="Close panel"]').click()`);
    assert.equal(await evaluate(`!!document.querySelector('.cad-studio')`), false);
    await evaluate(`[...document.querySelectorAll('.feature-card')].find(button => button.textContent.includes('3D studio')).click()`);
    await until(() => evaluate(`document.querySelector('.cad-viewport')?.dataset.modelLoaded === 'true' && document.querySelector('.cad-stats')?.textContent.includes('36.11')`));
    result.reopened_history_and_preview_without_rebuild = true;
    await evaluate(`document.querySelector('.cad-ai').open = true; const input = document.querySelector('.cad-ai textarea'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set.call(input, 'An open enclosure'); input.dispatchEvent(new Event('input', { bubbles: true }))`);
    await until(() => evaluate(`!document.querySelector('.cad-ai button').disabled`));
    await evaluate(`document.querySelector('.cad-ai button').click()`);
    await until(() => evaluate(`document.querySelector('.cad-error')?.textContent.includes('not configured yet')`));
    assert.equal(await evaluate(`document.querySelector('.cad-viewport').dataset.modelLoaded`), 'true');
    result.optional_planner_missing_key_preserves_offline_preview = true;

    // Exercise actual scene editing, object lifecycle, transformed/material GLB and restore.
    window.setContentSize(1440, 1000);
    await evaluate(`document.querySelectorAll('.cad-shapes button')[3].click()`);
    await until(() => evaluate(`document.querySelectorAll('.scene-roster button').length === 2`));
    assert.equal(await evaluate(`document.querySelector('.cad-builder select option[value="blender"]').disabled`), true);
    await evaluate(`document.querySelector('.scene-actions button').click()`);
    await until(() => evaluate(`document.querySelectorAll('.scene-roster button').length === 3`));
    await evaluate(`document.querySelector('[aria-label="Duplicate object"]').click()`);
    await until(() => evaluate(`document.querySelectorAll('.scene-roster button').length === 4`));
    await evaluate(`document.querySelector('[aria-label="Remove object"]').click()`);
    await until(() => evaluate(`document.querySelectorAll('.scene-roster button').length === 3`));
    await evaluate(`const selects = document.querySelectorAll('.scene-editor select'); selects[0].value='enclosure'; selects[0].dispatchEvent(new Event('change',{bubbles:true})); selects[1].value='titanium'; selects[1].dispatchEvent(new Event('change',{bubbles:true}));`);
    for (const [label,value] of [['rotation Z','45'],['position Y','20'],['position Z','40'],['scale X','1.2']]) {
      await evaluate(`{ const sceneInput=document.querySelector('[aria-label="${label}"]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(sceneInput,'${value}'); sceneInput.dispatchEvent(new Event('input',{bubbles:true})); }`);
    }
    await evaluate(`document.querySelector('.cad-build').click()`);
    await until(() => evaluate(`document.querySelector('.cad-status strong')?.textContent === 'Ready to explore' && document.querySelector('.cad-stats')?.textContent.includes('331.33') && document.querySelector('.cad-viewport')?.dataset.modelLoaded === 'true'`));
    await evaluate(`if(document.querySelector('.cad-preview-top button').getAttribute('aria-pressed') === 'true') document.querySelector('.cad-preview-top button').click(); document.querySelector('.cad-studio').scrollTop=0; document.querySelector('.cad-studio').parentElement.scrollTop=0;`);
    await sleep(400);
    fs.writeFileSync(path.join(output,'scene-desktop.png'),(await window.webContents.capturePage()).toPNG());
    await evaluate(`document.querySelectorAll('.cad-export button')[1].click()`);
    await until(() => downloads.length === 4);
    const sceneBinary = fs.readFileSync(downloads[3]);
    const loaded = await new Promise((resolve,reject) => new GLTFLoader().parse(sceneBinary.buffer.slice(sceneBinary.byteOffset,sceneBinary.byteOffset+sceneBinary.byteLength),'',resolve,reject));
    const parts=[]; loaded.scene.traverse(object => { if(object.isMesh) parts.push(object); });
    assert.equal(parts.length,3);
    assert.deepEqual(parts.map(part => part.material.name),['cyan','amber','titanium']);
    assert.ok(parts[2].geometry.attributes.position.count > parts[0].geometry.attributes.position.count);
    result.scene = { objects:3, materials:parts.map(part => part.material.name), add_duplicate_remove:true, transforms:true, real_glb_download:true };
    for (const width of [390,768]) {
      window.setContentSize(width,900); await sleep(200);
      assert.equal(await evaluate(`document.documentElement.scrollWidth > innerWidth || document.querySelector('.cad-studio').scrollWidth > document.querySelector('.cad-studio').clientWidth`),false);
      if(width===390) {
        await evaluate(`document.querySelector('.cad-studio').scrollTop=0; document.querySelector('.cad-studio').parentElement.scrollTop=0;`);
        fs.writeFileSync(path.join(output,'scene-mobile.png'),(await window.webContents.capturePage()).toPNG());
        await evaluate(`document.querySelector('.cad-workbench').scrollIntoView({block:'start'})`);
        await sleep(200);
        fs.writeFileSync(path.join(output,'scene-mobile-preview.png'),(await window.webContents.capturePage()).toPNG());
      }
    }
    await evaluate(`document.querySelector('[aria-label="Close panel"]').click()`);
    await evaluate(`[...document.querySelectorAll('.feature-card')].find(button => button.textContent.includes('3D studio')).click()`);
    await until(() => evaluate(`document.querySelectorAll('.scene-roster button').length === 3 && document.querySelector('.cad-viewport')?.dataset.modelLoaded === 'true' && document.querySelector('.cad-stats')?.textContent.includes('331.33')`));
    result.scene.restored_without_rebuild = true;
    result.passed = true;
  } catch (error) {
    result.passed = false;
    result.error = error.stack;
  }
  fs.writeFileSync(path.join(output, 'ui-verification.json'), JSON.stringify(result, null, 2));
  // Close through the actual titlebar/preload/native control bridge.
  await evaluate(`window.electronAPI.close()`);
};
require('../electron/native-main.cjs');
