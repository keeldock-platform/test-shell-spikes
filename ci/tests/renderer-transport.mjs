import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const listeners = new Map();
const writes = [];
let shutdown;
const source = fs.readFileSync(new URL('../../apps/desktop/web/bootstrap.js', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '').replace('export async function', 'async function').split('\nstart().catch')[0];
const sandbox = {
  URLSearchParams, URL, Set, Promise, Error,
  document: { querySelector() { return {}; } },
  window: { location: { search: '?spike=s11&case=S11-WINDOWS-LIVE' },
    addEventListener(type, callback) { listeners.set(type, callback); } },
  invoke(command, args) {
    assert.equal(command, 'record_renderer_event');
    let resolve, reject;
    const promise = new Promise((yes,no) => { resolve=yes; reject=no; });
    writes.push({ payload:JSON.parse(args.payload), resolve,reject });
    return promise;
  },
  listen(type, callback) { shutdown=callback; return Promise.resolve(() => {}); },
};
vm.createContext(sandbox); vm.runInContext(source,sandbox);
assert.equal(listeners.size,2);
for (const type of ['shell-spike:frame','shell-spike:event']) listeners.get(type)({detail:{sequence:7}});
assert.equal(writes.length,2);
for (const row of writes) {
  assert.equal(row.payload.spike,'s11'); assert.equal(row.payload.caseId,'S11-WINDOWS-LIVE');
  assert.equal(row.payload.detail.sequence,7);
}
let flushed=false;
const flush=sandbox.window.shellSpikeFlush().then(() => { flushed=true; });
await Promise.resolve(); assert.equal(flushed,false);
writes[0].resolve(); await Promise.resolve(); assert.equal(flushed,false);
writes[1].resolve(); await flush; assert.equal(flushed,true);
const stopped=shutdown();
await new Promise(resolve => setImmediate(resolve));
assert.equal(writes[2].payload.type,'shell-spike:shutdown-flushed');
writes[2].resolve(); await stopped;
listeners.get('shell-spike:event')({detail:{name:'failure'}});
writes[3].reject(new Error('disk unavailable'));
await assert.rejects(sandbox.window.shellSpikeFlush(),/disk unavailable/);
console.log('Renderer transport: listeners, payload, pending-write flush, shutdown acknowledgement and failure propagation passed.');
