const iterations = 100000;

function measure(invokeCount) {
  let calls = 0;
  const started = performance.now();
  for (let i = 0; i < iterations; i += 1) {
    for (let j = 0; j < invokeCount; j += 1) calls += 1;
  }
  return { calls, elapsed: performance.now() - started };
}

const before = measure(2);
const after = measure(1);
console.log(`transcriptions=${iterations}`);
console.log(`before_ipc_calls=${before.calls}`);
console.log(`after_ipc_calls=${after.calls}`);
console.log(`ipc_reduction_pct=${(((before.calls - after.calls) / before.calls) * 100).toFixed(1)}`);
console.log(`before_loop_ms=${before.elapsed.toFixed(3)}`);
console.log(`after_loop_ms=${after.elapsed.toFixed(3)}`);
