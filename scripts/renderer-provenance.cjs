// Build-only Rollup/Vite observer. Records raw inputs and final on-disk outputs.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const hash = raw => crypto.createHash('sha256').update(raw).digest('hex');
const MANIFEST = 'renderer-provenance.json';
const posix = value => value.split(path.sep).join('/');

function files(directory) {
  if (!fs.existsSync(directory)) return [];
  const result = [];
  function visit(current) {
    const stat = fs.lstatSync(current);
    if (stat.isSymbolicLink() || fs.realpathSync(current) !== current) throw Error('Linked renderer input/output');
    if (stat.isDirectory()) for (const name of fs.readdirSync(current).sort()) visit(path.join(current, name));
    else if (stat.isFile() && stat.nlink === 1) result.push(current);
    else throw Error('Shared or unsupported renderer entry');
    if (result.length > 20000) throw Error('Renderer inventory exceeded');
  }
  visit(directory);
  return result;
}

function rendererProvenance() {
  let root, out, config, graph, chunks, workerCount = 0;
  const workerGraphs = [], workerChunks = [];
  const inputs = new Map();
  const record = file => {
    file = path.resolve(file);
    const relative = posix(path.relative(root, file));
    if (relative.startsWith('../') || path.isAbsolute(relative) || fs.realpathSync(file) !== file) throw Error('Renderer input outside owned source');
    const stat = fs.statSync(file);
    if (!stat.isFile() || stat.nlink !== 1 || stat.size > 536870912) throw Error('Invalid renderer input');
    const value = {path: relative, bytes: stat.size, sha256: hash(fs.readFileSync(file))};
    const old = inputs.get(relative);
    if (old && JSON.stringify(old) !== JSON.stringify(value)) throw Error('Renderer input changed during build');
    inputs.set(relative, value);
    return relative;
  };
  const physical = id => {
    if (id.includes('\0')) return null;
    const file = id.split('?')[0];
    return path.isAbsolute(file) && fs.existsSync(file) && fs.statSync(file).isFile() ? path.resolve(file) : null;
  };
  const moduleId = (id, target) => {
    const file = physical(id);
    return target + '|' + (file ? record(file) + (id.includes('?') ? '?' + id.split('?').slice(1).join('?') : '')
      : 'virtual:' + hash(id.replaceAll(root, '<root>').replaceAll(posix(root), '<root>')));
  };
  const capture = (context, bundle, target) => ({
    graph: [...context.getModuleIds()].map(id => {
      const info = context.getModuleInfo(id);
      return {id: moduleId(id, target), target, path: physical(id) ? record(physical(id)) : null,
        imports: [...info.importedIds, ...info.dynamicallyImportedIds].map(id => moduleId(id, target)).sort(), external: info.isExternal};
    }),
    chunks: Object.values(bundle).filter(item => item.type === 'chunk').map(item => ({path: item.fileName, target, modules: Object.keys(item.modules).map(id => moduleId(id, target)).sort()})),
  });
  const plugin = {
    name: 'inara-renderer-provenance', apply: 'build', enforce: 'pre',
    configResolved(value) {
      config = value; root = path.resolve(config.root); out = path.resolve(root, config.build.outDir);
      if (out !== path.join(root, 'dist') || path.resolve(config.publicDir) !== path.join(root, 'public') || config.build.ssr || config.build.watch) throw Error('Unsupported provenance build layout');
      if (fs.realpathSync(root) !== root || (fs.existsSync(out) && fs.realpathSync(out) !== out)) throw Error('Linked renderer build root');
    },
    buildStart() {
      inputs.clear(); graph = null; chunks = null; workerGraphs.length = 0; workerChunks.length = 0; workerCount = 0;
      for (const folder of ['src', 'public', 'assets']) for (const file of files(path.join(root, folder))) record(file);
      for (const name of ['index.html', 'package.json', 'package-lock.json', 'vite.config.js', 'postcss.config.js', 'tailwind.config.js', 'scripts/renderer-provenance.cjs', 'docs/ASSET_OWNERSHIP.json']) record(path.join(root, name));
      for (const name of ['vite', 'rollup']) record(path.join(root, 'node_modules', name, 'package.json'));
    },
    load(id) { const file = physical(id); if (file) record(file); return null; },
    writeBundle(_options, bundle) {
      const main = capture(this, bundle, 'main');
      graph = [...main.graph, ...workerGraphs].sort((a,b) => a.id.localeCompare(b.id));
      chunks = [...main.chunks, ...workerChunks].sort((a,b) => a.path.localeCompare(b.path));
    },
    closeBundle() {
      if (!graph || !chunks) return; // An earlier build failure must never mint a manifest.
      for (const item of [...inputs.values()]) record(path.join(root, item.path));
      const publicCopies = files(path.join(root, 'public')).map(file => {
        const name = posix(path.relative(path.join(root, 'public'), file));
        const input = inputs.get('public/' + name);
        const output = path.join(out, name);
        if (!fs.existsSync(output) || hash(fs.readFileSync(output)) !== input.sha256) throw Error('Copied public asset changed/collided');
        return {input: input.path, output: name, sha256: input.sha256, bytes: input.bytes};
      });
      const outputs = files(out).map(file => ({path: posix(path.relative(out,file)), bytes: fs.statSync(file).size, sha256: hash(fs.readFileSync(file))}));
      if (outputs.some(item => item.path === MANIFEST)) throw Error('Stale renderer manifest');
      const copies = outputs.flatMap(output => [...inputs.values()].filter(input => input.sha256 === output.sha256 && input.bytes === output.bytes).map(input => ({input: input.path, output: output.path, sha256: input.sha256, bytes: input.bytes})));
      const copiedInputs = new Set(copies.map(item => item.input));
      const manifest = {format: 1, kind: 'inara-renderer-build', coverage: 'observed-rollup-graph',
        tooling: Object.fromEntries(['vite','rollup'].map(name => [name, JSON.parse(fs.readFileSync(path.join(root,'node_modules',name,'package.json'),'utf8')).version])),
        inputs: [...inputs.values()].sort((a,b) => a.path.localeCompare(b.path)), graph, chunks, public_copies: publicCopies, byte_identical_copies: copies,
        assets: [...inputs.values()].filter(item => copiedInputs.has(item.path) || /\.(png|ico|svg|jpe?g|webp|wasm|task|woff2?|ttf|glb|gltf|stl|mp[34]|wav|bin)$/i.test(item.path)).sort((a,b) => a.path.localeCompare(b.path)),
        ownership_registry: JSON.parse(fs.readFileSync(path.join(root,'docs/ASSET_OWNERSHIP.json'),'utf8')), outputs,
        reproducible_build_claimed: false, redistribution_cleared: false};
      const raw = JSON.stringify(manifest, null, 2) + '\n';
      if (Buffer.byteLength(raw) > 8388608) throw Error('Renderer provenance exceeds its bound');
      fs.writeFileSync(path.join(out,MANIFEST), raw, {flag:'wx'});
    },
  };
  return {plugin, workerPlugin() {
    const target = 'worker-' + (++workerCount);
    return {name: 'inara-worker-provenance', enforce: 'pre',
      load(id) { const file = physical(id); if (file) record(file); return null; },
      generateBundle(_options, bundle) {
        const captured = capture(this, bundle, target);
        workerGraphs.push(...captured.graph); workerChunks.push(...captured.chunks);
      },
    };
  }};
}
module.exports = {rendererProvenance, files};
