#!/usr/bin/env node
import { readFileSync, writeFileSync } from "fs";
import { execSync } from "child_process";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const version = process.argv[2];

if (!version || !/^\d+\.\d+\.\d+$/.test(version)) {
  console.error("Uso: npm run bump <versione>\nEsempio: npm run bump 0.2.0");
  process.exit(1);
}

function updateJson(filePath, key) {
  const full = resolve(root, filePath);
  const json = JSON.parse(readFileSync(full, "utf-8"));
  const old = json[key];
  json[key] = version;
  writeFileSync(full, JSON.stringify(json, null, 2) + "\n");
  console.log(`  ${filePath}: ${old} -> ${version}`);
}

function updateToml(filePath) {
  const full = resolve(root, filePath);
  let content = readFileSync(full, "utf-8");
  const match = content.match(/^version\s*=\s*"([^"]+)"/m);
  const old = match ? match[1] : "?";
  content = content.replace(/^(version\s*=\s*)"[^"]+"/m, `$1"${version}"`);
  writeFileSync(full, content);
  console.log(`  ${filePath}: ${old} -> ${version}`);
}

console.log(`\nBump versione a ${version}:\n`);

updateJson("package.json", "version");
updateJson("src-tauri/tauri.conf.json", "version");
updateToml("src-tauri/Cargo.toml");

console.log("\nAggiorno package-lock.json...");
execSync("npm install --package-lock-only", { cwd: root, stdio: "inherit" });

console.log(`\nFatto! Versione aggiornata a ${version} in tutti i file.\n`);
