export function nextReleaseVersion(publishedTag, level = "patch") {
  const match = /^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.exec(publishedTag);
  if (!match) throw new Error("Invalid published stable version");
  const [major, minor, patch] = match.slice(1).map(Number);
  if (level === "patch") return `${major}.${minor}.${patch + 1}`;
  if (level === "minor") return `${major}.${minor + 1}.0`;
  if (level === "major") return `${major + 1}.0.0`;
  throw new Error("Unknown release level");
}

export function validateReleaseVersion(publishedTag, requested, level = "patch") {
  const expected = nextReleaseVersion(publishedTag, level);
  if (requested !== expected) {
    throw new Error(`Latest published stable: ${publishedTag}. Expected next ${level}: ${expected}; received ${requested}.`);
  }
}

export function updateCargoLockVersion(contents, version) {
  const packageVersion = /(name = "Traflix-Voice"\r?\nversion = )"[^"]+"/;
  if (!packageVersion.test(contents)) throw new Error("Application entry missing from Cargo.lock");
  return contents.replace(packageVersion, `$1"${version}"`);
}
