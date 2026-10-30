// Main-only local DSH plugin. No dependency on a globally installed JS package.
import { spawn } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, readdir, readFile, writeFile, rename, unlink } from 'node:fs/promises';
import { resolve, join, isAbsolute } from 'node:path';

export const name = 'danus-main-checkpoints';

export function checkpointRequest(config, sessionId, turnId, env = process.env, signal) {
  return new Promise((resolveRequest, reject) => {
    const timeoutMs = config.timeoutMs ?? Number(env.DANUS_SNAPSHOT_TIMEOUT_SECONDS ?? 120) * 1000;
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) { reject(new Error('invalid snapshot timeout')); return; }
    const child = spawn(config.python, ['-m', 'danus.checkpoints', 'request-all',
      '--session-id', sessionId, '--turn-id', String(turnId)], {
      cwd: config.cwd, env, stdio: ['ignore', 'pipe', 'pipe'], detached: process.platform !== 'win32',
    });
    let output = ''; let diagnostic = ''; let kill; let cancelled = false;
    child.stdout.on('data', (chunk) => { output = (output + chunk.toString()).slice(-1048576); });
    child.stderr.on('data', (chunk) => { diagnostic = (diagnostic + chunk.toString()).slice(-16384); });
    const killOwned = (signal) => {
      try {
        if (process.platform !== 'win32' && child.pid) process.kill(-child.pid, signal);
        else child.kill(signal);
      } catch (error) { if (error.code !== 'ESRCH') reject(error); }
    };
    const cancel = () => {
      cancelled = true;
      killOwned('SIGTERM');
      kill ??= setTimeout(() => killOwned('SIGKILL'), 250);
    };
    const timeout = setTimeout(cancel, timeoutMs);
    signal?.addEventListener('abort', cancel, { once: true });
    if (signal?.aborted) cancel();
    const cleanup = () => {
      clearTimeout(timeout); clearTimeout(kill);
      signal?.removeEventListener('abort', cancel);
    };
    child.once('error', (error) => { cleanup(); reject(error); });
    child.once('close', (code, exitSignal) => {
      cleanup();
      if (cancelled) killOwned('SIGKILL');
      if (diagnostic.trim()) process.stderr.write(`[danus checkpoint] ${diagnostic.trim()}\n`);
      if (code !== 0 || cancelled) {
        if (output.trim()) process.stderr.write(`[danus checkpoint] ${output.trim().slice(-16384)}\n`);
        reject(new Error(`checkpoint request ${cancelled ? 'cancelled/timed out' : `exited ${code ?? exitSignal}`}`)); return;
      }
      try {
        const rows = JSON.parse(output || '[]');
        if (!Array.isArray(rows)) throw new Error('invalid checkpoint response');
        const errors = rows.filter((row) => row.error);
        if (errors.length) throw new Error(JSON.stringify(errors));
        if (output.trim()) process.stderr.write(`[danus checkpoint] ${output.trim().slice(-16384)}\n`);
        resolveRequest();
      } catch (error) { reject(error); }
    });
  });
}

// Intents contain only root session/turn identifiers, never project data. Atomic
// publication makes interrupted checkpoints retryable on the next plugin mount.
export function pendingStore(directory) {
  if (!directory || !isAbsolute(directory)) throw new Error('pendingDir must be absolute');
  const root = resolve(directory);
  const pathFor = ({ sessionId, turnId }) => join(root, `${createHash('sha256').update(JSON.stringify([sessionId, turnId])).digest('hex')}.json`);
  return {
    async load() {
      await mkdir(root, { recursive: true, mode: 0o700 });
      const rows = [];
      for (const file of await readdir(root)) {
        if (!/^[a-f0-9]{64}\.json$/.test(file)) continue;
        const row = JSON.parse(await readFile(join(root, file), 'utf8'));
        if (!row || typeof row.sessionId !== 'string' || !row.sessionId || !Number.isSafeInteger(row.turnId) || row.turnId < 0
            || Object.keys(row).some((key) => !['sessionId', 'turnId'].includes(key)) || pathFor(row) !== join(root, file)) throw new Error('invalid pending checkpoint intent');
        rows.push(row);
      }
      return rows;
    },
    async put(row) {
      await mkdir(root, { recursive: true, mode: 0o700 });
      // Both paths are checked descendants of the configured absolute directory.
      const target = pathFor(row); const temporary = `${target}.${process.pid}.tmp`;
      await writeFile(temporary, JSON.stringify(row), { mode: 0o600 });
      await rename(temporary, target);
    },
    async done(row) {
      // pathFor only returns a SHA-256 filename inside the verified root.
      await unlink(pathFor(row)).catch((error) => { if (error.code !== 'ENOENT') throw error; });
    },
  };
}

// Queue ownership is explicit. Web work gets a generous timeout; teardown drains
// briefly, cancels any owned child, and leaves durable intents for next startup.
export function createCheckpointHook(config, {
  env = process.env,
  request = (sessionId, turnId, signal) => checkpointRequest(config, sessionId, turnId, env, signal),
  report = (error) => process.stderr.write(`[danus checkpoint] ${error.message ?? error}\n`),
  store = config.pendingDir ? pendingStore(config.pendingDir) : undefined,
} = {}) {
  const seen = new Set(); const controller = new AbortController();
  let closed = false;
  const safeReport = (error) => { try { report(error); } catch { /* Never kill reasoning. */ } };
  const perform = async (row) => {
    try {
      await store?.put(row);
      if (controller.signal.aborted) return;
      await request(row.sessionId, row.turnId, controller.signal);
      await store?.done(row);
    } catch (error) { safeReport(error); }
  };
  let pending = Promise.resolve().then(async () => {
    if (env.DANUS_SNAPSHOT_AUTO === '0' || config.role !== 'main') return;
    for (const row of await store?.load() ?? []) {
      const key = JSON.stringify([row.sessionId, row.turnId]);
      if (seen.has(key)) continue;
      seen.add(key);
      await perform(row);
    }
  }).catch(safeReport);
  const onEvent = (session, event) => {
    if (closed || env.DANUS_SNAPSHOT_AUTO === '0' || config.role !== 'main') return;
    const header = session?.header;
    if (!header || header.parentSession || header.origin === 'subagent' || (header.delegationDepth ?? 0) > 0) return;
    if (config.sessionId && session.id !== config.sessionId) return;
    if (config.preset && header.agentPreset !== config.preset) return;
    if (event?.type !== 'turn/end' || event.data?.reason?.kind !== 'completed') return;
    const turn = event.data.turn;
    if (!session.id || !Number.isSafeInteger(turn) || turn < 0) return;
    const key = JSON.stringify([session.id, turn]);
    if (seen.has(key)) return;
    seen.add(key);
    const row = { sessionId: session.id, turnId: turn };
    // Persist at admission, not after older requests, so backlog survives exit.
    const saved = Promise.resolve().then(() => store?.put(row));
    saved.catch(safeReport);
    pending = pending.then(async () => { await saved; await perform(row); }).catch(safeReport);
  };
  return {
    onEvent,
    flush: () => pending,
    dispose: async () => {
      closed = true;
      let timer;
      const drained = await Promise.race([pending.then(() => true), new Promise((resolveWait) => {
        timer = setTimeout(() => resolveWait(false), config.shutdownGraceMs ?? 3500);
      })]);
      clearTimeout(timer);
      if (!drained) {
        safeReport(new Error('shutdown checkpoint grace elapsed; pending intents retained for next main launch'));
        controller.abort();
        await pending;
      }
    },
  };
}

export function apply(ctx, config) {
  if (config.role !== 'main') return;
  const hook = createCheckpointHook(config);
  const stop = ctx.on('session/event', hook.onEvent);
  ctx.effect(() => async () => { stop(); await hook.dispose(); });
}
