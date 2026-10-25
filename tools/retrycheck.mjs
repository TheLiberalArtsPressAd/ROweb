// Failure/retry smoke test: load with the manifest missing, confirm the client
// shows the error screen, restore the file, press R, and wait for "ready".
//
//   python tools/serve.py 8080 docs      (in another terminal)
//   node tools/retrycheck.mjs
//
// Exits 0 only if the error screen appeared *and* the client recovered without
// a page reload.
import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync, renameSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const url = "http://127.0.0.1:8080/index.html";
const manifest = join(ROOT, "docs/assets/manifest.json");
const hidden = `${manifest}.hold`;
const port = 9334;
const edge = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";

renameSync(manifest, hidden);

const profile = mkdtempSync(join(tmpdir(), "roweb-edge-"));
const proc = spawn(edge, [
  "--headless=new", "--no-sandbox", "--use-angle=swiftshader",
  "--enable-unsafe-swiftshader", "--disable-extensions", "--mute-audio",
  "--window-size=1280,720", `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`, "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function target() {
  for (let i = 0; i < 80; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return page;
    } catch {}
    await sleep(250);
  }
  throw new Error("devtools never came up");
}

const page = await target();
const ws = new WebSocket(page.webSocketDebuggerUrl);
let nextId = 1;
const pending = new Map();
const logs = [];
ws.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
    return;
  }
  if (msg.method === "Runtime.consoleAPICalled") {
    logs.push(`[${msg.params.type}] ${msg.params.args.map((a) => a.value ?? a.description ?? a.type).join(" ")}`);
  } else if (msg.method === "Log.entryAdded") {
    logs.push(`[${msg.params.level}] ${msg.params.entry.text}`);
  }
});
await new Promise((res, rej) => {
  ws.addEventListener("open", res, { once: true });
  ws.addEventListener("error", rej, { once: true });
});
const send = (method, params = {}) => {
  const id = nextId++;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
};

await send("Runtime.enable");
await send("Log.enable");
await send("Page.enable");
await send("Page.navigate", { url });

// Wait for the client to give up on the missing manifest.
const failDeadline = Date.now() + 90000;
while (Date.now() < failDeadline && !logs.some((l) => l.includes("could not load"))) await sleep(1000);
const failed = logs.some((l) => l.includes("could not load"));
const shot1 = await send("Page.captureScreenshot", { format: "png" });
writeFileSync(join(ROOT, "out/retry_fail.png"), Buffer.from(shot1.data, "base64"));

// Restore the asset and press R.
renameSync(hidden, manifest);
await sleep(500);
for (const type of ["keyDown", "keyUp"]) {
  await send("Input.dispatchKeyEvent", { type, key: "r", code: "KeyR", windowsVirtualKeyCode: 82, nativeVirtualKeyCode: 82, text: type === "keyDown" ? "r" : undefined });
  await sleep(120);
}

const okDeadline = Date.now() + 120000;
while (Date.now() < okDeadline && !logs.some((l) => l.includes("ready"))) await sleep(1500);
const ready = logs.some((l) => l.includes("ready"));
const shot2 = await send("Page.captureScreenshot", { format: "png" });
writeFileSync(join(ROOT, "out/retry_ok.png"), Buffer.from(shot2.data, "base64"));

console.log(logs.join("\n"));
console.log(`\n--- failure shown: ${failed}; recovered without reload: ${ready}`);
if (!existsSync(manifest)) console.log("WARNING: manifest not restored");
ws.close();
proc.kill();
process.exit(failed && ready ? 0 : 1);
