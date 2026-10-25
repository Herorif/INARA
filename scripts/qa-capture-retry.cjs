// QA helper for the hidden-renderer verify scripts: some GPUs/drivers make
// webContents.capturePage() throw a transient "UnknownVizError" right after a
// page loads. Load this once at the top of a verify script (before any window
// exists) to retry those captures instead of failing the whole run.
const { app } = require('electron');

const RETRIES = 20;
const DELAY_MS = 250;

app.on('web-contents-created', (_event, contents) => {
  const original = contents.capturePage.bind(contents);
  contents.capturePage = async (...args) => {
    for (let attempt = 0; ; attempt++) {
      try {
        return await original(...args);
      } catch (error) {
        if (!String(error && error.message).includes('UnknownVizError') || attempt >= RETRIES) throw error;
        await new Promise(resolve => setTimeout(resolve, DELAY_MS));
      }
    }
  };
});
