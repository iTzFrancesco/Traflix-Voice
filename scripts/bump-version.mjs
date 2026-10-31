#!/usr/bin/env node
import { readFileSync, writeFileSync } from "fs";
import { execFileSync } from "child_process";
import { validateReleaseVersion, updateCargoLockVersion } from "./release-version-policy.mjs";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const version = process.argv[2];

if (!version || !/^\d+\.\d+\.\d+$/.test(version)) {
  console.error("Uso: npm run bump <versione>\nEsempio: npm run bump -- 1.8.2");
  process.exit(1);
}

const level = process.argv.includes("--major") ? "major" : process.argv.includes("--minor") ? "minor" : "patch";
try {
  const publishedTag = execFileSync("gh", ["api", "repos/{owner}/{repo}/releases/latest", "--jq", ".tag_name"], {
    cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"],
  }).trim();
  validateReleaseVersion(publishedTag, version, level);
  console.log(`Base: latest published stable ${publishedTag}; release level: ${level}.`);
} catch (error) {
  console.error(error.message);
  console.error("No version files changed. Verify GitHub access; advancing minor/major requires an explicit user request.");
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

const packageLockPath = resolve(root, "package-lock.json");
const packageLock = JSON.parse(readFileSync(packageLockPath, "utf-8"));
packageLock.version = version;
packageLock.packages[""].version = version;
writeFileSync(packageLockPath, JSON.stringify(packageLock, null, 2) + "\n");
const cargoLockPath = resolve(root, "src-tauri/Cargo.lock");
const cargoLock = readFileSync(cargoLockPath, "utf-8");
writeFileSync(cargoLockPath, updateCargoLockVersion(cargoLock, version));
console.log(`\nVersion files and lockfiles updated to ${version}.\n`);
