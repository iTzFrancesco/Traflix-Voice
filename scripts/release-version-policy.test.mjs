import test from "node:test";
import assert from "node:assert/strict";
import { nextReleaseVersion, validateReleaseVersion, updateCargoLockVersion } from "./release-version-policy.mjs";

test("compatible releases stay on the published stable series by default", () => {
  assert.equal(nextReleaseVersion("v1.8.1"), "1.8.2");
  assert.doesNotThrow(() => validateReleaseVersion("v1.8.1", "1.8.2"));
  for (const version of ["1.8.1", "1.8.3", "1.9.0", "1.10.0", "2.0.0"]) {
    assert.throws(() => validateReleaseVersion("v1.8.1", version));
  }
});

test("explicit series changes still cannot skip an unpublished series", () => {
  assert.doesNotThrow(() => validateReleaseVersion("v1.8.1", "1.9.0", "minor"));
  assert.throws(() => validateReleaseVersion("v1.8.1", "1.10.0", "minor"));
  assert.doesNotThrow(() => validateReleaseVersion("v1.8.1", "2.0.0", "major"));
});

test("release policy rejects drafts and malformed base versions", () => {
  for (const base of ["android-v0.1.34", "v1.8.2-draft", "1.08.1", "main"]) {
    assert.throws(() => nextReleaseVersion(base));
  }
});

test("Cargo lock updates preserve dependency versions on Linux and Windows", () => {
  for (const newline of ["\n", "\r\n"]) {
    const contents = ['[[package]]', 'name = "Traflix-Voice"', 'version = "1.8.1"', '', '[[package]]', 'name = "dependency"', 'version = "2.3.4"'].join(newline);
    const updated = updateCargoLockVersion(contents, "1.8.2");
    assert.match(updated, /version = "1.8.2"/);
    assert.match(updated, /version = "2.3.4"/);
    assert.equal(updated.split(newline).length, contents.split(newline).length);
  }
  assert.throws(() => updateCargoLockVersion('name = "other"', "1.8.2"));
});
