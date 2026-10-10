const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

const elements = new Map();
const requests = [];
const element = (id) => {
  if (!elements.has(id)) elements.set(id, {
    value: '', textContent: '', innerHTML: '', disabled: false,
    classList: { add() {}, remove() {}, toggle() {} },
    querySelectorAll() { return []; },
  });
  return elements.get(id);
};
const context = vm.createContext({
  document: {
    getElementById: element,
    querySelectorAll: (selector) => selector.includes('input:checked') ? [{ value: 'remotion' }] : [],
  },
  fetch: async (path, opts = {}) => {
    requests.push({ path, body: opts.body && JSON.parse(opts.body) });
    const result = path === '/api/tts/vieneu/voices'
      ? { ready: true, default: 'Hải Đăng', voices: [{ key: 'Mai Anh', label: 'Mai Anh' }] }
      : path === '/api/podcast/voices' ? { voices: [], default: 'mai' }
      : path === '/api/jobs' && opts.method === 'POST' ? { id: 'test-job' }
      : [];
    return { ok: true, json: async () => result };
  },
  setInterval() {}, setTimeout() {}, clearTimeout() {},
});
vm.runInContext(fs.readFileSync('factory/web/app.js', 'utf8'), context);

(async () => {
  vm.runInContext(`showSpec({id:'test', title:'Thử giọng', voice:'vi-VN-NamMinhNeural',
    scenes:[{type:'next', title:'Kết', say:'Xin chào.'}]}, 'test.json')`, context);
  assert.equal(element('ttsProvider').value, 'edge');
  element('ttsProvider').value = 'vieneu';
  await element('ttsProvider').onchange();
  element('vieneuVoice').value = 'Mai Anh';
  element('vieneuVoice').oninput();
  let spec = JSON.parse(element('specJson').value);
  assert.equal(spec.tts_provider, 'vieneu');
  assert.equal(spec.vieneu_voice, 'Mai Anh');
  assert.equal(spec.voice, 'vi-VN-NamMinhNeural');
  assert.match(element('vieneuVoices').innerHTML, /Mai Anh/);
  await element('btnSaveSpec').onclick();
  const saved = requests.find(r => r.path === '/api/content/test.json');
  assert.equal(saved.body.tts_provider, 'vieneu');
  assert.equal(saved.body.vieneu_voice, 'Mai Anh');
  // Opening a different script and switching back must preserve both voice namespaces.
  vm.runInContext(`showSpec({id:'second', title:'Giọng khác', voice:'vi-VN-NamMinhNeural',
    tts_provider:'vieneu', vieneu_voice:'Custom preset',
    scenes:[{type:'next', title:'Kết', say:'Xin chào.'}]}, 'second.json')`, context);
  assert.equal(element('vieneuVoice').value, 'Custom preset');
  element('ttsProvider').value = 'edge';
  await element('ttsProvider').onchange();
  spec = JSON.parse(element('specJson').value);
  assert.equal(spec.tts_provider, 'edge');
  assert.equal(spec.voice, 'vi-VN-NamMinhNeural');
  assert.equal(spec.vieneu_voice, 'Custom preset');
  console.log('TTS UI: provider selection, preset discovery, persistence, and voice switching passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
