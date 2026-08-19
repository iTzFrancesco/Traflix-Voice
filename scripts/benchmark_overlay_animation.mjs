const frames = 100000;
const count = 14;
const maxHeight = 30;

function makeBars() {
  return Array.from({ length: count }, () => ({ style: {} }));
}

function measureBefore() {
  const bars = makeBars();
  const heights = new Array(count).fill(3);
  const targets = new Array(count).fill(3);
  let phase = 0;
  let currentVolume = 36;
  const started = performance.now();
  for (let frame = 0; frame < frames; frame += 1) {
    const volNorm = Math.min(1, Math.max(0, currentVolume / 100));
    for (let i = 0; i < count; i += 1) {
      const center = count / 2;
      const dist = Math.abs(i - center) / center;
      const bellFactor = 1 - dist * 0.5;
      const jitter = 0.6 + Math.random() * 0.4;
      targets[i] = 3 + volNorm * (maxHeight - 3) * bellFactor * jitter;
      heights[i] += (targets[i] - heights[i]) * 0.25;
      const height = Math.max(3, Math.min(maxHeight, heights[i]));
      bars[i].style.height = `${height}px`;
      bars[i].style.boxShadow = `0 0 ${(height / maxHeight) * 6}px rgba(255, 190, 90, ${0.3 + (height / maxHeight) * 0.4})`;
    }
    phase += 0.05;
    currentVolume += (50 - currentVolume) * 0.01;
  }
  return performance.now() - started + phase + bars[0].style.height.length;
}

function measureAfter() {
  const bars = makeBars();
  const heights = new Array(count).fill(3);
  const bellFactors = Array.from({ length: count }, (_, i) => {
    const center = count / 2;
    return 1 - (Math.abs(i - center) / center) * 0.5;
  });
  let phase = 0;
  let currentVolume = 36;
  const started = performance.now();
  for (let frame = 0; frame < frames; frame += 1) {
    const volNorm = Math.min(1, Math.max(0, currentVolume / 100));
    for (let i = 0; i < count; i += 1) {
      const jitter = 0.6 + Math.random() * 0.4;
      const target = 3 + volNorm * (maxHeight - 3) * bellFactors[i] * jitter;
      heights[i] += (target - heights[i]) * 0.25;
      const height = Math.max(3, Math.min(maxHeight, heights[i]));
      bars[i].style.transform = `scaleY(${height / maxHeight})`;
    }
    phase += 0.05;
    currentVolume += (50 - currentVolume) * 0.01;
  }
  return performance.now() - started + phase + bars[0].style.transform.length;
}

for (let i = 0; i < 2; i += 1) {
  measureBefore();
  measureAfter();
}

const before = measureBefore();
const after = measureAfter();
console.log(`frames=${frames}`);
console.log(`before_ms=${before.toFixed(3)}`);
console.log(`after_ms=${after.toFixed(3)}`);
console.log(`reduction_pct=${(((before - after) / before) * 100).toFixed(1)}`);
