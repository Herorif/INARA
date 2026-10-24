// Send only lifecycle reasons across preload; never camera frames or handles.
function bindCaptureLifecycle(window, powerMonitor) {
  const subscriptions = [];
  const bind = (target,event,reason) => {
    const callback=()=>{if(!window.isDestroyed())window.webContents.send('capture-pause',reason);};
    target.on(event,callback);subscriptions.push(()=>target.removeListener(event,callback));
  };
  bind(window,'minimize','minimized');bind(window,'hide','hidden');
  bind(powerMonitor,'suspend','suspend');bind(powerMonitor,'lock-screen','locked');
  const cleanup=()=>{subscriptions.forEach(remove=>remove());};
  window.once('closed',cleanup);
  return cleanup;
}
module.exports={bindCaptureLifecycle};
