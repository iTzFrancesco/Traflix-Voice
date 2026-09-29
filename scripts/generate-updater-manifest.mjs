import { readdir, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const configPath = new URL("../src-tauri/tauri.conf.json", import.meta.url);
const bundleDirectory = fileURLToPath(
  new URL("../src-tauri/target/release/bundle/msi/", import.meta.url),
);
const config = JSON.parse(await readFile(configPath, "utf8"));
const version = config.version;
const tag = process.env.GITHUB_REF_NAME ?? process.argv[2] ?? "";
const repository = process.env.GITHUB_REPOSITORY ?? "iTzFrancesco/Traflix-Voice";

if (!/^v\d+\.\d+\.\d+$/.test(tag) || tag !== `v${version}`) {
  throw new Error(`Desktop release tag ${tag || "(missing)"} must match v${version}.`);
}

const updateBundles = (await readdir(bundleDirectory)).filter((name) =>
  name.toLowerCase().endsWith(".msi"),
);
if (updateBundles.length !== 1) {
  throw new Error(`Expected one signed MSI updater bundle, found ${updateBundles.length}.`);
}

const bundleName = updateBundles[0];
const signature = (
  await readFile(`${bundleDirectory}/${bundleName}.sig`, "utf8")
).trim();
if (!signature) throw new Error(`The updater signature for ${bundleName} is empty.`);

const releaseAssetName = bundleName.replaceAll(" ", ".");
const windowsMsi = {
  signature,
  url: `https://github.com/${repository}/releases/download/${tag}/${encodeURIComponent(releaseAssetName)}`,
};
const manifest = {
  version,
  notes: "Aggiornamento automatico di Traflix Voice per Windows.",
  pub_date: new Date().toISOString(),
  platforms: {
    "windows-x86_64": windowsMsi,
    "windows-x86_64-msi": windowsMsi,
  },
};

await writeFile(
  `${bundleDirectory}/latest.json`,
  `${JSON.stringify(manifest, null, 2)}\n`,
  "utf8",
);
console.log(`Generated Windows updater manifest for ${tag}.`);
