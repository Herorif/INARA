// Build-time only. The emitted native workspace needs Electron, not npm/Node.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const {builtinModules} = require('node:module');
const esbuild = require('esbuild');
const root = path.resolve(__dirname, '..');
const hash = file => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

async function main() {
  for (const relative of ['.runtime', '.runtime/desktop-bundles']) {
    const directory = path.join(root, relative);
    if (fs.existsSync(directory) && fs.realpathSync(directory) !== directory) throw Error('Linked bundle staging parent');
  }
  const output = path.join(root, '.runtime/desktop-bundles', crypto.randomUUID());
  fs.mkdirSync(output, {recursive:true});
  // The workspace and the talking overlay: each entry bundles its local modules and socket.io-client.
  const entries = ['native-main.cjs', 'overlay-main.cjs'];
  const preloads = ['preload.js', 'overlay-preload.js'];
  const results = [];
  for (const entry of entries) results.push(await esbuild.build({
    absWorkingDir:root, entryPoints:[`electron/${entry}`],
    outfile:path.join(output,entry), bundle:true, platform:'node', format:'cjs',
    external:['electron'], legalComments:'eof', metafile:true, write:true,
  }));
  const allowed = new Set(['electron', 'bufferutil', 'utf-8-validate', ...builtinModules, ...builtinModules.map(name=>`node:${name}`)]);
  const imports = results.flatMap(result=>Object.values(result.metafile.outputs).flatMap(value=>value.imports)).filter(value=>value.external).map(value=>value.path);
  if (imports.some(name=>!allowed.has(name))) throw Error('Unbundled workspace dependency');
  for (const name of preloads) fs.copyFileSync(path.join(root,'electron',name),path.join(output,name));
  const inputs = [...new Set([...results.flatMap(result=>Object.keys(result.metafile.inputs)), ...preloads.map(name=>`electron/${name}`)])].sort();
  const manifest = {
    format:1, kind:'native-workspace-bundle', electron_version:require('../node_modules/electron/package.json').version,
    esbuild_version:esbuild.version, node_runtime_required:false,
    optional_native_modules:['bufferutil','utf-8-validate'], external_imports:[...new Set(imports)].sort(),
    inputs:inputs.map(name=>({path:name,sha256:hash(path.join(root,name))})),
    files:[...entries, ...preloads].map(name=>({path:name,bytes:fs.statSync(path.join(output,name)).size,sha256:hash(path.join(output,name))})),
  };
  fs.writeFileSync(path.join(output,'bundle-manifest.json'),JSON.stringify(manifest,null,2));
  console.log(JSON.stringify({directory:path.relative(root,output),files:manifest.files.length,node_runtime_required:false}));
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
