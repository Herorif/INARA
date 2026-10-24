const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const {rendererProvenance, files} = require('../scripts/renderer-provenance.cjs');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(),'inara-renderer-test-'));
  t.after(() => {
    assert.ok(root.startsWith(path.join(os.tmpdir(),'inara-renderer-test-')));
    fs.rmSync(root,{recursive:true});
  });
  const put = (name, value='fixture') => { const file=path.join(root,name);fs.mkdirSync(path.dirname(file),{recursive:true});fs.writeFileSync(file,value);return file; };
  for(const name of ['index.html','package.json','package-lock.json','vite.config.js','postcss.config.js','tailwind.config.js','scripts/renderer-provenance.cjs','src/main.js']) put(name);
  put('docs/ASSET_OWNERSHIP.json','{"format":1,"entries":[]}');
  for(const name of ['vite','rollup']) put(`node_modules/${name}/package.json`,'{"version":"fixture"}');
  fs.mkdirSync(path.join(root,'public'));
  fs.mkdirSync(path.join(root,'assets'));
  put('dist/index.html','compiled HTML');put('dist/main.js','compiled JS');
  const observer=rendererProvenance(),plugin=observer.plugin;
  plugin.configResolved({root,publicDir:path.join(root,'public'),build:{outDir:'dist'}});
  plugin.buildStart();
  const id=path.join(root,'src/main.js');
  const context={getModuleIds:()=>[id],getModuleInfo:()=>({importedIds:[],dynamicallyImportedIds:[],isExternal:false})};
  const bundle={'main.js':{type:'chunk',fileName:'main.js',modules:{[id]:{}}}};
  const finish=()=>{plugin.writeBundle.call(context,{},bundle);plugin.closeBundle();};
  return {root,put,plugin,observer,finish};
}

test('main and worker output graphs include byte-identical WASM with no absolute path leak',t=>{
  const f=fixture(t),worker=f.observer.workerPlugin();
  const id=f.put('node_modules/vendor/worker.js','worker raw');
  worker.load(id);f.put('dist/worker.js','worker compiled');
  const context={getModuleIds:()=>[id],getModuleInfo:()=>({importedIds:[],dynamicallyImportedIds:[],isExternal:false})};
  worker.generateBundle.call(context,{}, {'worker.js':{type:'chunk',fileName:'worker.js',modules:{[id]:{}}}});
  const wasm=f.put('node_modules/vendor/runtime.wasm','wasm raw');
  worker.load(wasm+'?url');f.put('dist/runtime.wasm','wasm raw');
  f.finish();
  const raw=fs.readFileSync(path.join(f.root,'dist/renderer-provenance.json'),'utf8'),manifest=JSON.parse(raw);
  assert.equal(manifest.graph.length,2);assert.equal(manifest.chunks.length,2);
  assert.ok(manifest.assets.some(x=>x.path.endsWith('.wasm')));
  assert.ok(manifest.byte_identical_copies.some(x=>x.output==='runtime.wasm'));
  assert.equal(raw.includes(f.root),false);assert.equal(manifest.redistribution_cleared,false);
});

test('changed raw source refuses a manifest',t=>{
  const f=fixture(t);f.put('src/main.js','changed');
  assert.throws(f.finish,/changed during build/);
  assert.equal(fs.existsSync(path.join(f.root,'dist/renderer-provenance.json')),false);
});

test('copied public file drift refuses',t=>{
  const f=fixture(t);f.put('public/model.task','fixture model');
  // New input is observed by load, but output bytes still have to match.
  f.plugin.load(path.join(f.root,'public/model.task'));
  f.put('dist/model.task','wrong model');
  assert.throws(f.finish,/changed\/collided/);
});

test('failed builds never mint a manifest',t=>{
  const f=fixture(t);f.plugin.closeBundle();
  assert.equal(fs.existsSync(path.join(f.root,'dist/renderer-provenance.json')),false);
});

test('existing manifests are never silently overwritten',t=>{
  const f=fixture(t);f.finish();assert.throws(()=>f.plugin.closeBundle(),/Stale renderer manifest/);
});

test('shared files fail inventory',t=>{
  const f=fixture(t);fs.linkSync(path.join(f.root,'src/main.js'),path.join(f.root,'src/alias.js'));
  assert.throws(()=>files(path.join(f.root,'src')),/Shared/);
});
