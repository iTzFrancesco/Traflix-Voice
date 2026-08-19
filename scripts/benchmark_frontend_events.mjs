const iterations = 200000;
const volumePayload = JSON.stringify({ status: "volume", value: 42 });

function beforeHandler(payload) {
  const data = JSON.parse(payload);
  let pastePromise = null;
  if (data.status === "result" && data.text) pastePromise = Promise.resolve();
  if (["starting", "loading_model", "listening", "processing", "ready", "result", "error", "rate_limit"].includes(data.status || "")) {
    void data.status;
  }
  if (data.status === "listening") void data.status;
  else if (data.status === "result" || data.status === "ready") void data.status;
  if (data.status === "downloading") void data.status;
  if (data.status === "download_complete") void data.status;
  if (data.status === "download_error") void data.status;
  if (data.status === "error") void data.status;
  if (data.status === "rate_limit") void data.status;
  if (data.status === "gpu_info") void data.status;
  if (data.status === "volume") return pastePromise;
  return pastePromise;
}

const statuses = new Set(["starting", "loading_model", "listening", "processing", "ready", "result", "error", "rate_limit"]);

function afterHandler(payload) {
  if (payload.startsWith('{"status":"volume"') || payload.startsWith('{"status": "volume"')) return;
  const data = JSON.parse(payload);
  let pastePromise = null;
  if (data.status === "result" && data.text) pastePromise = Promise.resolve();
  if (statuses.has(data.status || "")) void data.status;
  if (data.status === "listening") void data.status;
  else if (data.status === "result" || data.status === "ready") void data.status;
  if (data.status === "downloading") void data.status;
  if (data.status === "download_complete") void data.status;
  if (data.status === "download_error") void data.status;
  if (data.status === "error") void data.status;
  if (data.status === "rate_limit") void data.status;
  if (data.status === "gpu_info") void data.status;
  return pastePromise;
}

function measure(handler) {
  const started = performance.now();
  for (let i = 0; i < iterations; i += 1) handler(volumePayload);
  return performance.now() - started;
}

for (let i = 0; i < 3; i += 1) {
  measure(beforeHandler);
  measure(afterHandler);
}

const before = measure(beforeHandler);
const after = measure(afterHandler);
console.log(`iterations=${iterations}`);
console.log(`before_ms=${before.toFixed(3)}`);
console.log(`after_ms=${after.toFixed(3)}`);
console.log(`reduction_pct=${(((before - after) / before) * 100).toFixed(1)}`);
