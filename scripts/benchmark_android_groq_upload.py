#!/usr/bin/env python3
"""Compile and run the Android multipart benchmark on a standalone JDK 17.

Supply an installed kotlinc or cached compiler jars. Nothing is downloaded.
The benchmark uses synthetic WAVs and loopback HTTP only, not Groq or Android
hardware. Evidence and temporary build files must stay outside the repository.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
HELPER_SOURCE = (
    REPO_ROOT
    / "src-tauri/gen/android/app/src/main/java/it/traflix/voice/GroqMultipartBody.kt"
)
BENCHMARK_SOURCE = REPO_ROOT / "scripts/android/GroqUploadBenchmarkTest.kt"
EVIDENCE_FILES = (
    "upload_profiles.tsv",
    "upload_samples.tsv",
    "upload_replay_checks.tsv",
    "upload_streaming_checks.tsv",
)


def outside_repository(path: Path, option: str) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        raise ValueError(f"{option} must be absolute")
    resolved = path.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise ValueError(f"{option} must be outside the repository")
    return resolved


def local_classpath(value: str) -> str:
    entries = []
    for entry in value.split(os.pathsep):
        if not entry:
            raise ValueError("Classpath entries must not be empty")
        path = Path(entry).expanduser().resolve()
        if not path.exists():
            raise ValueError(f"Classpath entry does not exist: {path}")
        entries.append(str(path))
    return os.pathsep.join(entries)


def jdk17(java_home: Path) -> tuple[Path, Path]:
    home = java_home.expanduser().resolve()
    java = home / "bin" / ("java.exe" if os.name == "nt" else "java")
    release = home / "release"
    if not java.is_file() or not release.is_file():
        raise ValueError("--java-home must point to an installed JDK 17")
    version = re.search(r'^JAVA_VERSION="([^"]+)"$', release.read_text(), re.MULTILINE)
    if version is None or version.group(1).split(".")[0] != "17":
        raise ValueError("This benchmark requires JDK 17")
    return home, java


def parse_args() -> tuple[argparse.ArgumentParser, argparse.Namespace]:
    parser = argparse.ArgumentParser(
        description=(
            "Run 20 multipart upload profiles offline on JDK 17, "
            "outside Android's test source set."
        ),
        epilog=(
            "Use local jars from an installed Kotlin distribution or an existing Gradle cache. "
            "The compiler classpath needs kotlin-compiler-embeddable, matching kotlin-stdlib "
            "and kotlin-script-runtime, the compiler's kotlin-reflect, trove4j, and JetBrains "
            "annotations. The test classpath needs kotlin-stdlib, JUnit 4, and hamcrest-core. "
            "Separate entries with the OS path separator and expand wildcards before calling. "
            "Inherited JVM option variables are ignored so only the supplied JDK and classpaths apply."
        ),
    )
    compiler = parser.add_mutually_exclusive_group(required=True)
    compiler.add_argument(
        "--compiler-classpath", help="Classpath of already installed compiler jars"
    )
    compiler.add_argument(
        "--kotlinc", type=Path, help="Path to an already installed kotlinc executable"
    )
    parser.add_argument(
        "--test-classpath", required=True,
        help="Classpath of local Kotlin stdlib, JUnit, and Hamcrest",
    )
    parser.add_argument(
        "--java-home", type=Path, required=True, help="Installed JDK 17 directory"
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True,
        help="Absolute evidence directory outside the repository",
    )
    parser.add_argument(
        "--scratch-dir", type=Path,
        help="Absolute temporary-build directory outside the repository",
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Allow replacing benchmark TSVs in the evidence directory",
    )
    return parser, parser.parse_args()


def run(args: argparse.Namespace) -> None:
    home, java = jdk17(args.java_home)
    test_classpath = local_classpath(args.test_classpath)
    output = outside_repository(args.output_dir, "--output-dir")
    scratch = outside_repository(
        args.scratch_dir or Path(tempfile.gettempdir()), "--scratch-dir"
    )
    if not args.overwrite and any((output / name).exists() for name in EVIDENCE_FILES):
        raise ValueError(
            "Evidence files already exist; choose a fresh --output-dir "
            "or explicitly use --overwrite"
        )
    if args.compiler_classpath is not None:
        compiler_classpath = local_classpath(args.compiler_classpath)
        compiler_command = [
            str(java), "-cp", compiler_classpath,
            "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler",
        ]
    else:
        kotlinc = args.kotlinc.expanduser().resolve()
        if not kotlinc.is_file():
            raise ValueError("--kotlinc must point to an installed compiler executable")
        compiler_command = [str(kotlinc)]
    for source in (HELPER_SOURCE, BENCHMARK_SOURCE):
        if not source.is_file():
            raise ValueError(f"Benchmark source is missing: {source.relative_to(REPO_ROOT)}")
    output.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    for name in (
        "JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "JAVA_OPTS",
        "KOTLIN_OPTS", "CLASSPATH",
    ):
        environment.pop(name, None)
    environment["JAVA_HOME"] = str(home)
    environment["PATH"] = str(home / "bin") + os.pathsep + environment.get("PATH", "")
    with tempfile.TemporaryDirectory(prefix="traflix-groq-upload-", dir=scratch) as temporary:
        build = Path(temporary)
        jar = build / "groq-upload-benchmark.jar"
        environment["TMPDIR"] = str(build)
        environment["TMP"] = str(build)
        environment["TEMP"] = str(build)
        if args.compiler_classpath is not None:
            compiler_command.insert(1, f"-Djava.io.tmpdir={build}")
        else:
            compiler_command.append(f"-J-Djava.io.tmpdir={build}")
        print(
            "Compiling the production helper and standalone benchmark "
            "with JVM target 1.8",
            flush=True,
        )
        subprocess.run(
            [
                *compiler_command,
                "-no-stdlib", "-no-reflect", "-jdk-home", str(home),
                "-jvm-target", "1.8", "-classpath", test_classpath, "-d", str(jar),
                str(HELPER_SOURCE), str(BENCHMARK_SOURCE),
            ],
            cwd=REPO_ROOT,
            env=environment,
            check=True,
            timeout=120,
        )
        environment["TRAFLIX_GROQ_UPLOAD_BENCHMARK"] = "1"
        environment["TRAFLIX_GROQ_UPLOAD_BENCHMARK_OUTPUT"] = str(output)
        print("Running the same 20 loopback profiles and transport checks", flush=True)
        subprocess.run(
            [
                str(java), f"-Djava.io.tmpdir={build}", "--add-modules", "jdk.httpserver",
                "-cp", str(jar) + os.pathsep + test_classpath,
                "org.junit.runner.JUnitCore", "it.traflix.voice.GroqUploadBenchmarkTest",
            ],
            cwd=REPO_ROOT,
            env=environment,
            check=True,
            timeout=180,
        )
    if not all((output / name).is_file() for name in EVIDENCE_FILES):
        raise ValueError("Benchmark completed without all expected evidence files")
    print(f"Evidence written to {output}")


def main() -> int:
    parser, args = parse_args()
    try:
        run(args)
    except subprocess.CalledProcessError as error:
        return error.returncode if error.returncode > 0 else 1
    except subprocess.TimeoutExpired:
        parser.exit(1, "error: Standalone JVM command timed out\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"error: {error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
