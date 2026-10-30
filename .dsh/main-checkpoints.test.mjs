import test from 'node:test';
import assert from 'node:assert/strict';
import { createCheckpointHook, apply, checkpointRequest, pendingStore } from './main-checkpoints.mjs';
import { mkdtemp, readdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const root = { id: 'main-session', header: { id: 'main-session' } };
const end = (turn = 1, kind = 'completed') => ({ type: 'turn/end', data: { turn, reason: { kind } } });

test('one checkpoint per completed root turn, never a step or tool', async () => {
  const calls = [];
  const hook = createCheckpointHook({ role: 'main' }, { env: {}, request: async (...args) => calls.push(args.slice(0, 2)) });
  for (const type of ['step/end', 'tool/result', 'assistant/message']) hook.onEvent(root, { ...end(), type });
  for (const kind of ['error', 'aborted', 'interrupted', 'cancelled']) hook.onEvent(root, end(1, kind));
  hook.onEvent(root, end()); hook.onEvent(root, end()); hook.onEvent(root, end(2));
  await hook.flush();
  assert.deepEqual(calls, [['main-session', 1], ['main-session', 2]]);
});

test('speculative children and non-main roles never checkpoint', async () => {
  const calls = [];
  const deps = { env: {}, request: async (...args) => calls.push(args.slice(0, 2)) };
  for (const role of ['worker', 'verifier', 'write-paper', 'human-summary']) {
    const hook = createCheckpointHook({ role }, deps); hook.onEvent(root, end()); await hook.flush();
  }
  const hook = createCheckpointHook({ role: 'main' }, deps);
  for (const header of [{ parentSession: 'main-session' }, { origin: 'subagent' }, { delegationDepth: 1 }]) {
    hook.onEvent({ id: 'child', header }, end());
  }
  hook.onEvent({ id: 'missing-header' }, end());
  await hook.flush(); assert.deepEqual(calls, []);
});

test('explicit auto opt-out and root identity filtering', async () => {
  let calls = 0;
  for (const [config, env] of [[{ role: 'main' }, { DANUS_SNAPSHOT_AUTO: '0' }], [{ role: 'main', sessionId: 'other' }, {}]]) {
    const hook = createCheckpointHook(config, { env, request: async () => calls++ });
    hook.onEvent(root, end()); await hook.flush();
  }
  assert.equal(calls, 0);
});

test('errors are reported, queue continues, dispose drains and stops delivery', async () => {
  const calls = []; const errors = [];
  let release;
  const first = new Promise((resolve) => { release = resolve; });
  const hook = createCheckpointHook({ role: 'main' }, { env: {},
    request: async (_session, turn) => { calls.push(turn); if (turn === 1) { await first; throw new Error('disk full'); } },
    report: (error) => errors.push(error.message),
  });
  hook.onEvent(root, end(1)); hook.onEvent(root, end(2));
  const disposing = hook.dispose(); hook.onEvent(root, end(3));
  await new Promise((resolve) => setImmediate(resolve)); assert.deepEqual(calls, [1]);
  release(); await disposing;
  assert.deepEqual(calls, [1, 2]); assert.deepEqual(errors, ['disk full']);
});

test('DSH apply registers supervised asynchronous disposal', async () => {
  let listener; let dispose; let stopped = false;
  const ctx = { on(type, fn) { assert.equal(type, 'session/event'); listener = fn; return () => { stopped = true; }; }, effect(fn) { dispose = fn(); } };
  apply(ctx, { role: 'worker' }); assert.equal(listener, undefined);
  apply(ctx, { role: 'main' }); assert.equal(typeof listener, 'function');
  await dispose(); assert.equal(stopped, true);
});

test('failed child launch rejects instead of escaping the supervisor', async () => {
  await assert.rejects(checkpointRequest({ python: '/no-such-danus-python', cwd: process.cwd() }, 'root', 1), /ENOENT/);
});

test('durable pending intents retry after failure and skip when auto disabled', async () => {
  const directory = await mkdtemp(join(tmpdir(), 'danus-hook-'));
  const store = pendingStore(directory); const errors = []; const calls = [];
  const failed = createCheckpointHook({ role: 'main' }, { env: {}, store,
    request: async () => { throw new Error('busy'); }, report: (error) => errors.push(error.message) });
  failed.onEvent(root, end()); await failed.flush();
  assert.deepEqual(await store.load(), [{ sessionId: root.id, turnId: 1 }]);
  const disabled = createCheckpointHook({ role: 'main' }, { store, env: { DANUS_SNAPSHOT_AUTO: '0' }, request: async () => calls.push('bad') });
  await disabled.dispose(); assert.deepEqual(calls, []);
  const resumed = createCheckpointHook({ role: 'main' }, { store, env: {}, request: async (session, turn) => calls.push([session, turn]) });
  await resumed.dispose(); assert.deepEqual(calls, [[root.id, 1]]);
  assert.deepEqual(await store.load(), []); assert.deepEqual(errors, ['busy']);
});

test('shutdown cancellation retains pending intents rather than killing reasoning', async () => {
  const rows = new Map(); const errors = [];
  const store = { load: async () => [], put: async (row) => rows.set(row.turnId, row), done: async (row) => rows.delete(row.turnId) };
  const hook = createCheckpointHook({ role: 'main', shutdownGraceMs: 10 }, { env: {}, store,
    request: (_session, _turn, signal) => new Promise((_resolve, reject) => signal.addEventListener('abort', () => reject(new Error('cancelled')), { once: true })),
    report: (error) => errors.push(error.message),
  });
  hook.onEvent(root, end()); await hook.dispose();
  assert.equal(rows.size, 1); assert.ok(errors.some((message) => message.includes('retained')));
});

test('pending store validates input and ignores unrelated files', async () => {
  assert.throws(() => pendingStore('../escape'), /absolute/);
  const directory = await mkdtemp(join(tmpdir(), 'danus-hook-schema-'));
  const store = pendingStore(directory);
  await writeFile(join(directory, 'unrelated.json'), 'not JSON');
  assert.deepEqual(await store.load(), []);
  await writeFile(join(directory, `${'a'.repeat(64)}.json`), JSON.stringify({ sessionId: '../outside', turnId: 'bad' }));
  await assert.rejects(store.load(), /invalid pending/);
  assert.equal((await readdir(directory)).length, 2);
});

test('Web preset filtering excludes other root roles', async () => {
  const calls = [];
  const hook = createCheckpointHook({ role: 'main', preset: 'danus-main' }, { env: {}, request: async (session) => calls.push(session) });
  hook.onEvent({ ...root, header: { agentPreset: 'other' } }, end());
  hook.onEvent({ ...root, header: { agentPreset: 'danus-main' } }, end());
  await hook.flush(); assert.deepEqual(calls, [root.id]);
});
