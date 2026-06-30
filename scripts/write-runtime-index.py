#!/usr/bin/env python3
import argparse
import hashlib
import json
import pathlib
import tarfile


MANIFEST_NAME = "SimpleGraphicRuntime.json"
RUNTIME_PREFIX = "SimpleGraphicRuntime-"
LEGACY_WINDOWS_ARCHIVE = "SimpleGraphicDLLs-x64-windows.tar"

KNOWN_ARCHITECTURES = {
    "x64",
    "x86",
    "arm64",
    "arm64ec",
    "arm64x",
    "arm",
    "armv6",
    "armv7",
    "riscv32",
    "riscv64",
    "riscv128",
    "ppc",
    "ppc64",
    "ppc64le",
    "mips",
    "mips64",
    "s390",
    "s390x",
    "loongarch32",
    "loongarch64",
    "ia64",
}


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def normalize_platform_label(platform: str) -> str:
    platform = platform.lower()
    if platform in {"darwin", "mac", "macos", "osx"}:
        return "macos"
    if platform in {"windows", "win", "win32"} or platform.startswith(("mingw", "msys", "cygwin")):
        return "win32"
    return platform


def normalize_architecture_label(architecture: str) -> str:
    architecture = architecture.lower()
    aliases = {
        "amd64": "x64",
        "x86_64": "x64",
        "aarch64": "arm64",
        "armhf": "armv7",
        "i386": "x86",
        "i486": "x86",
        "i586": "x86",
        "i686": "x86",
        "ppc64el": "ppc64le",
    }
    if architecture.startswith("armv7"):
        return "armv7"
    if architecture.startswith("armv6"):
        return "armv6"
    if architecture.startswith("armv5"):
        return "arm"
    return aliases.get(architecture, architecture)


def is_known_architecture(architecture: str) -> bool:
    return normalize_architecture_label(architecture) in KNOWN_ARCHITECTURES


def split_runtime_archive_target(path: pathlib.Path) -> tuple[str, str, str]:
    name = path.name
    for suffix in (".tar.gz", ".tgz", ".tar"):
        if name.endswith(suffix):
            stem = name[: -len(suffix)]
            break
    else:
        fail(f"{name} is not a supported runtime archive")

    if not stem.startswith(RUNTIME_PREFIX):
        fail(f"{name} does not start with {RUNTIME_PREFIX}")

    target = stem[len(RUNTIME_PREFIX) :]
    if target.count("-") != 1:
        fail(f"{name} target must be a two-part <platform>-<architecture> value")

    first, second = target.split("-", 1)
    if is_known_architecture(first):
        platform = normalize_platform_label(second)
        architecture = normalize_architecture_label(first)
    else:
        platform = normalize_platform_label(first)
        architecture = normalize_architecture_label(second)

    if not platform or not architecture:
        fail(f"{name} target must include both platform and architecture")

    return f"{platform}-{architecture}", platform, architecture


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_member_name(name: str) -> str:
    path = pathlib.PurePosixPath(name)
    parts = [part for part in path.parts if part not in ("", ".")]
    return "/".join(parts)


def clean_member_name(member: tarfile.TarInfo, archive_path: pathlib.Path) -> str:
    member_path = pathlib.PurePosixPath(member.name)
    if member_path.is_absolute() or ".." in member_path.parts:
        fail(f"unsafe path in {archive_path.name}: {member.name}")
    clean = member.name
    while clean.startswith("./"):
        clean = clean[2:]
    return "" if clean in ("", ".") else clean.rstrip("/")


def validate_archive_members(path: pathlib.Path, members: list[tarfile.TarInfo]) -> None:
    link_member_paths: set[pathlib.PurePosixPath] = set()
    for member in members:
        member_path = pathlib.PurePosixPath(member.name)
        clean = clean_member_name(member, path)
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            fail(f"{path.name} contains unsafe member type: {member.name}")
        if member.issym() or member.islnk():
            link_path = pathlib.PurePosixPath(member.linkname)
            if link_path.is_absolute() or ".." in link_path.parts:
                fail(f"{path.name} contains unsafe link: {member.name} -> {member.linkname}")
            if "/" in member.linkname.strip("/"):
                fail(f"{path.name} archive links must stay flat: {member.name} -> {member.linkname}")
            link_member_paths.add(member_path)
        if not clean:
            continue
        if clean == ".DS_Store" or clean.startswith("._"):
            fail(f"{path.name} must not contain macOS metadata files: {clean}")
        if member.isdir():
            fail(f"{path.name} must not contain directories: {member.name}")
        if "/" in clean:
            fail(f"{path.name} must be flat: {member.name}")

    for member in members:
        member_path = pathlib.PurePosixPath(member.name)
        for link_member_path in link_member_paths:
            if link_member_path != member_path and link_member_path in member_path.parents:
                fail(
                    f"{path.name} contains member that would extract through "
                    f"link {link_member_path}: {member.name}"
                )


def read_runtime_manifest(path: pathlib.Path) -> dict:
    with tarfile.open(path) as archive:
        members = archive.getmembers()
        validate_archive_members(path, members)
        manifest_members = [
            member
            for member in members
            if normalized_member_name(member.name) == MANIFEST_NAME
        ]
        if len(manifest_members) != 1:
            fail(f"{path.name} must contain exactly one {MANIFEST_NAME}")
        manifest_file = archive.extractfile(manifest_members[0])
        if manifest_file is None:
            fail(f"{path.name} {MANIFEST_NAME} is not a regular file")
        try:
            manifest = json.load(manifest_file)
        except json.JSONDecodeError as exc:
            fail(f"{path.name} has invalid {MANIFEST_NAME}: {exc}")
    if not isinstance(manifest, dict):
        fail(f"{path.name} {MANIFEST_NAME} must be a JSON object")
    return manifest


def require_manifest_value(manifest: dict, path: pathlib.Path, key: str, expected: object) -> None:
    actual = manifest.get(key)
    if actual != expected:
        fail(f"{path.name} manifest field {key!r} expected {expected!r}, got {actual!r}")


def require_manifest_list(manifest: dict, path: pathlib.Path, key: str) -> list[str]:
    value = manifest.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        fail(f"{path.name} manifest field {key!r} must be a string list")
    return value


def runtime_archive_entry(path: pathlib.Path) -> dict:
    target, platform, architecture = split_runtime_archive_target(path)
    manifest = read_runtime_manifest(path)

    require_manifest_value(manifest, path, "schemaVersion", 1)
    require_manifest_value(manifest, path, "name", "SimpleGraphic")
    require_manifest_value(manifest, path, "target", target)
    require_manifest_value(manifest, path, "platform", platform)
    require_manifest_value(manifest, path, "architecture", architecture)

    entry_library = manifest.get("entryLibrary")
    if not isinstance(entry_library, str) or not entry_library:
        fail(f"{path.name} manifest field 'entryLibrary' must be a non-empty string")

    build_type = manifest.get("buildType")
    if not isinstance(build_type, str) or not build_type:
        fail(f"{path.name} manifest field 'buildType' must be a non-empty string")

    layout = manifest.get("layout")
    if not isinstance(layout, str) or not layout:
        fail(f"{path.name} manifest field 'layout' must be a non-empty string")

    return {
        "fileName": path.name,
        "target": target,
        "platform": platform,
        "architecture": architecture,
        "buildType": build_type,
        "layout": layout,
        "entryLibrary": entry_library,
        "entrypoints": require_manifest_list(manifest, path, "entrypoints"),
        "luaModules": require_manifest_list(manifest, path, "luaModules"),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def archive_checksum_entry(path: pathlib.Path, mode: str, target: str, platform: str, architecture: str) -> dict:
    return {
        "fileName": path.name,
        "target": target,
        "platform": platform,
        "architecture": architecture,
        "mode": mode,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def runtime_archives_from_dir(artifact_dir: pathlib.Path) -> list[pathlib.Path]:
    archives: list[pathlib.Path] = []
    for pattern in (
        "SimpleGraphicRuntime-*.tar",
        "SimpleGraphicRuntime-*.tar.gz",
        "SimpleGraphicRuntime-*.tgz",
    ):
        archives.extend(artifact_dir.glob(pattern))
    return sorted(set(archives), key=lambda path: path.name)


def write_index(output: pathlib.Path | None, index: dict) -> None:
    text = json.dumps(index, indent=2, sort_keys=True) + "\n"
    if output:
        output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Write a SimpleGraphic runtime release index")
    parser.add_argument("archives", nargs="*", type=pathlib.Path)
    parser.add_argument("--artifact-dir", type=pathlib.Path)
    parser.add_argument("--legacy-windows-archive", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    archives = list(args.archives)
    legacy_archive = args.legacy_windows_archive
    if args.artifact_dir:
        if archives:
            fail("pass either runtime archives or --artifact-dir, not both")
        if not args.artifact_dir.is_dir():
            fail(f"artifact directory does not exist: {args.artifact_dir}")
        archives = runtime_archives_from_dir(args.artifact_dir)
        if legacy_archive is None:
            legacy_archive = args.artifact_dir / LEGACY_WINDOWS_ARCHIVE

    if not archives:
        fail("no runtime archives were provided")

    runtime_entries = []
    seen_targets: dict[str, str] = {}
    for path in sorted(archives, key=lambda item: item.name):
        entry = runtime_archive_entry(path)
        target = entry["target"]
        if target in seen_targets:
            fail(
                f"duplicate runtime archive target {target}: "
                f"{seen_targets[target]} and {path.name}"
            )
        seen_targets[target] = path.name
        runtime_entries.append(entry)
    index = {
        "schemaVersion": 1,
        "name": "SimpleGraphic",
        "runtimeArchives": sorted(runtime_entries, key=lambda item: item["target"]),
    }

    if legacy_archive and legacy_archive.is_file():
        index["legacyArchives"] = [
            archive_checksum_entry(
                legacy_archive,
                "legacy-windows-runtime",
                "win32-x64",
                "win32",
                "x64",
            )
        ]

    write_index(args.output, index)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
