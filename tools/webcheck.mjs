// Headless browser check for the exported web build.
// Launches Edge with the DevTools protocol, records console output, and grabs
// a screenshot once the game reports it is ready (or after a timeout).
//
//   node tools/webcheck.mjs [url] [out.png] [waitSeconds]

import { spawn } from "node:child_process";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const url = process.argv[2] || "http://127.0.0.1:8080/index.html";
const out = process.argv[3] || "D:/ROweb/out/web_shot.png";
const waitSeconds = Number(process.argv[4] || 60);
const port = 9333;
const edge = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";

const profile = mkdtempSync(join(tmpdir(), "roweb-edge-"));
const proc = spawn(edge, [
  "--headless=new",
  "--no-sandbox",
  "--use-angle=swiftshader",
  "--enable-unsafe-swiftshader",
  "--disable-extensions",
  "--mute-audio",
  "--window-size=1280,720",
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,
  "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function targets() {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/list`);
      const list = await r.json();
      const page = list.find((t) => t.type === "page");
      if (page) return page;
    } catch {}
    await sleep(250);
  }
  throw new Error("devtools never came up");
}

const page = await targets();
const ws = new WebSocket(page.webSocketDebuggerUrl);
let nextId = 1;
const pending = new Map();
const logs = [];

ws.addEventListener("message", (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    if (msg.error) reject(new Error(JSON.stringify(msg.error)));
    else resolve(msg.result);
    return;
  }
  if (msg.method === "Runtime.consoleAPICalled") {
    const text = msg.params.args.map((a) => a.value ?? a.description ?? a.type).join(" ");
    logs.push(`[${msg.params.type}] ${text}`);
  } else if (msg.method === "Runtime.exceptionThrown") {
    const d = msg.params.exceptionDetails;
    logs.push(`[exception] ${d.text} ${d.exception?.description ?? ""}`);
  } else if (msg.method === "Log.entryAdded") {
    const e = msg.params.entry;
    logs.push(`[${e.level}] ${e.text} ${e.url ?? ""}`);
  }
});

await new Promise((res, rej) => {
  ws.addEventListener("open", res, { once: true });
  ws.addEventListener("error", rej, { once: true });
});

function send(method, params = {}) {
  const id = nextId++;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

await send("Runtime.enable");
await send("Log.enable");
await send("Page.enable");
await send("Page.navigate", { url });

const deadline = Date.now() + waitSeconds * 1000;
let ready = false;
while (Date.now() < deadline) {
  await sleep(1500);
  if (logs.some((l) => l.includes("selftest:") || l.includes("ready"))) ready = true;
  if (ready) break;
}

const zoom = Number(process.env.ZOOM || 0);
if (zoom !== 0) {
  for (let i = 0; i < Math.abs(zoom); i++) {
    await send("Input.dispatchMouseEvent", {
      type: "mouseWheel",
      x: 620,
      y: 320,
      deltaX: 0,
      deltaY: zoom > 0 ? -120 : 120,
    });
    await sleep(120);
  }
  await sleep(1800);
}

const res = await send("Page.captureScreenshot", { format: "png" });
writeFileSync(out, Buffer.from(res.data, "base64"));

console.log(logs.join("\n"));
console.log(`\n--- ${ready ? "ready" : "timeout"} after ${waitSeconds}s, screenshot: ${out}`);

ws.close();
proc.kill();
process.exit(0);
