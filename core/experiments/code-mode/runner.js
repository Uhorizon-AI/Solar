// Permissionless subprocess bridge. The host owns the catalog, data and audit.
const decoder = new TextDecoder();
const encoder = new TextEncoder();
let pending = "";
async function* lines() {
  for await (const chunk of Deno.stdin.readable) {
    pending += decoder.decode(chunk, { stream: true });
    let index;
    while ((index = pending.indexOf("\n")) >= 0) {
      const line = pending.slice(0, index);
      pending = pending.slice(index + 1);
      yield JSON.parse(line);
    }
  }
}
const input = lines();
const { value: packet } = await input.next();
const source = `
let serial = 0;
const waiting = new Map();
const send = globalThis.postMessage.bind(globalThis);
// Ordinary console output must not corrupt the JSON-lines RPC transport.
for (const name of ["log", "info", "debug", "warn"]) {
  console[name] = console.error.bind(console);
}
globalThis.onmessage = async ({data}) => {
  if (data.type === "reply") {
    const waiter = waiting.get(data.id);
    if (!waiter) return;
    waiting.delete(data.id);
    data.error ? waiter.reject(new Error(data.error)) : waiter.resolve(data.result);
    return;
  }
  if (data.type !== "start") return;
  const solar = Object.freeze(Object.fromEntries(data.methods.map(name => [name,
    args => new Promise((resolve, reject) => {
      const id = ++serial;
      waiting.set(id, {resolve, reject});
      send({type: "call", id, method: name, arguments: args});
    })])));
  try {
    const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
    const result = await new AsyncFunction("solar", '"use strict";\\n' + data.code)(solar);
    send({type: "done", result: result ?? null});
  } catch (error) {
    send({type: "failed", error: String(error.message)});
  }
};`;
const worker = new Worker(`data:application/javascript,${encodeURIComponent(source)}`, {
  type: "module", deno: { permissions: "none" },
});
// Ordinary worker logs go to discarded stderr; only messages use this bridge.
let writes = Promise.resolve();
worker.onmessage = ({ data }) => {
  writes = writes.then(async () => {
    const bytes = encoder.encode(JSON.stringify(data) + "\n");
    let offset = 0;
    while (offset < bytes.length) offset += await Deno.stdout.write(bytes.subarray(offset));
    if (data.type === "done" || data.type === "failed") Deno.exit(0);
  });
};
worker.onerror = () => Deno.exit(1);
worker.postMessage({ type: "start", ...packet });
for await (const reply of input) worker.postMessage(reply);
