/** Optional device-local synthesis. No remote voice is selected or auto-downloaded. */
export class LocalSpeech {
  constructor({
    synth = globalThis.speechSynthesis,
    Utterance = globalThis.SpeechSynthesisUtterance
  } = {}) {
    this.synth = synth;
    this.Utterance = Utterance;
    this.generation = 0;
  }
  stop() {
    this.generation++;
    this.synth?.cancel();
    this.finish?.();
    this.finish = null;
  }
  async speak(text) {
    this.stop();
    const generation = this.generation;
    const voice = this.synth?.getVoices().find(voice => voice.localService);
    if (!voice || !this.Utterance) throw Error('No local speech voice is ready. The text answer is still available.');
    const utterance = new this.Utterance(text.slice(0, 4000));
    utterance.voice = voice;
    await new Promise((resolve, reject) => {
      this.finish = resolve;
      utterance.onend = () => {
        if (generation === this.generation) this.finish = null;
        resolve();
      };
      utterance.onerror = () => {
        if (generation === this.generation) this.finish = null;
        generation === this.generation ? reject(Error('Local playback stopped. Read the text answer or try again.')) : resolve();
      };
      this.synth.speak(utterance);
    });
  }
}
