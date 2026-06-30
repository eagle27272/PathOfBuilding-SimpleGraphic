#!/usr/bin/env python3
import argparse
import ctypes
import json
import os
import platform as platform_module
import pathlib
import subprocess
import sys
import tarfile
import tempfile


MANIFEST_NAME = "SimpleGraphicRuntime.json"
DEFAULT_ENTRYPOINT = "RunLuaFileAsConsole"


def fail(message: str) -> None:
    raise SystemExit(f"error: {message}")


def normalized_member_path(name: str) -> pathlib.PurePosixPath:
    path = pathlib.PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        fail(f"unsafe path in archive: {name}")
    return pathlib.PurePosixPath(*[part for part in path.parts if part not in ("", ".")])


def ensure_within(root: pathlib.Path, path: pathlib.Path, message: str) -> None:
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError:
        fail(message)


def validate_members(archive: tarfile.TarFile, root: pathlib.Path) -> None:
    for member in archive.getmembers():
        member_path = normalized_member_path(member.name)
        if not member_path.parts:
            continue
        destination = root.joinpath(*member_path.parts)
        ensure_within(root, destination, f"unsafe path in archive: {member.name}")
        if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
            fail(f"unsafe member type in archive: {member.name}")
        if member.issym() or member.islnk():
            link_path = pathlib.PurePosixPath(member.linkname)
            if link_path.is_absolute() or ".." in link_path.parts:
                fail(f"unsafe link in archive: {member.name} -> {member.linkname}")
            ensure_within(
                root,
                destination.parent.joinpath(*link_path.parts),
                f"unsafe link in archive: {member.name} -> {member.linkname}",
            )


def read_manifest(root: pathlib.Path) -> dict:
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        fail(f"archive did not extract {MANIFEST_NAME}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"{MANIFEST_NAME} is invalid JSON: {exc}")
    if not isinstance(manifest, dict):
        fail(f"{MANIFEST_NAME} must be a JSON object")
    return manifest


def require_manifest_string(manifest: dict, field: str) -> str:
    value = manifest.get(field)
    if not isinstance(value, str) or not value:
        fail(f"{MANIFEST_NAME} field {field!r} must be a non-empty string")
    return value


def normalize_architecture(value: str) -> str:
    value = value.lower()
    aliases = {
        "amd64": "x64",
        "x86_64": "x64",
        "aarch64": "arm64",
        "i386": "x86",
        "i486": "x86",
        "i586": "x86",
        "i686": "x86",
        "armhf": "armv7",
        "ppc64el": "ppc64le",
    }
    if value.startswith("armv7"):
        return "armv7"
    if value.startswith("armv6"):
        return "armv6"
    if value.startswith("armv5"):
        return "arm"
    return aliases.get(value, value)


def host_target() -> tuple[str, str]:
    if sys.platform == "darwin":
        host_platform = "macos"
    elif sys.platform.startswith("linux"):
        host_platform = "linux"
    elif sys.platform == "win32":
        host_platform = "win32"
    else:
        host_platform = sys.platform
    return host_platform, normalize_architecture(platform_module.machine())


def targets_match(manifest: dict) -> bool:
    archive_platform = require_manifest_string(manifest, "platform")
    archive_architecture = normalize_architecture(require_manifest_string(manifest, "architecture"))
    local_platform, local_architecture = host_target()
    return archive_platform == local_platform and archive_architecture == local_architecture


def target_label(platform: str, architecture: str) -> str:
    return f"{platform}-{normalize_architecture(architecture)}"


def extract_archive(archive_path: pathlib.Path, root: pathlib.Path) -> dict:
    with tarfile.open(archive_path) as archive:
        validate_members(archive, root)
        archive.extractall(root)
    return read_manifest(root)


def add_library_search_path(root: pathlib.Path):
    if os.name == "nt" and hasattr(os, "add_dll_directory"):
        return os.add_dll_directory(str(root))
    return None


def call_entrypoint(library_path: pathlib.Path, entrypoint: str, script_path: pathlib.Path) -> int:
    dll_directory = add_library_search_path(library_path.parent)
    try:
        library = ctypes.CDLL(str(library_path))
        try:
            function = getattr(library, entrypoint)
        except AttributeError:
            fail(f"{library_path.name} does not export {entrypoint}")

        function.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_char_p)]
        function.restype = ctypes.c_int
        argv = (ctypes.c_char_p * 1)(str(script_path).encode("utf-8"))
        return int(function(1, argv))
    finally:
        if dll_directory is not None:
            dll_directory.close()


def run_entrypoint_child(library_path: pathlib.Path, entrypoint: str, script_path: pathlib.Path) -> int:
    command = [
        sys.executable,
        str(pathlib.Path(__file__).resolve()),
        "--entrypoint-child",
        str(library_path),
        entrypoint,
        str(script_path),
    ]
    return subprocess.run(command, cwd=library_path.parent).returncode


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test a packaged SimpleGraphic runtime archive")
    parser.add_argument("archive", type=pathlib.Path)
    parser.add_argument("--entrypoint", default=DEFAULT_ENTRYPOINT)
    parser.add_argument("--script", type=pathlib.Path)
    parser.add_argument("--keep-extracted", type=pathlib.Path)
    parser.add_argument(
        "--allow-incompatible-host",
        action="store_true",
        help="validate extraction but skip entrypoint execution when the archive target cannot run on this host",
    )
    return parser.parse_args()


def run_smoke(args: argparse.Namespace, root: pathlib.Path) -> int | None:
    manifest = extract_archive(args.archive, root)
    entry_library = require_manifest_string(manifest, "entryLibrary")
    library_path = root / entry_library
    if not library_path.is_file():
        fail(f"entry library is missing after extraction: {entry_library}")

    archive_platform = require_manifest_string(manifest, "platform")
    archive_architecture = require_manifest_string(manifest, "architecture")
    local_platform, local_architecture = host_target()
    if not targets_match(manifest):
        archive_target = target_label(archive_platform, archive_architecture)
        local_target = target_label(local_platform, local_architecture)
        if args.allow_incompatible_host:
            print(
                f"Skipped smoke execution for {args.archive.name}: "
                f"archive target {archive_target} is incompatible with host {local_target}"
            )
            return None
        fail(
            f"archive target {archive_target} cannot be smoke-tested on host {local_target}; "
            "rerun on a matching host or pass --allow-incompatible-host"
        )

    runtime_work_dir = root / "SimpleGraphic"
    runtime_work_dir.mkdir(exist_ok=True)
    script_path = args.script
    if script_path:
        script_path = script_path.resolve()
        if not script_path.is_file():
            fail(f"smoke script does not exist: {script_path}")
    else:
        script_path = root / "simplegraphic-smoke.lua"
        script_path.write_text("Exit()\n", encoding="utf-8")

    previous_cwd = pathlib.Path.cwd()
    try:
        os.chdir(root)
        return run_entrypoint_child(library_path, args.entrypoint, script_path)
    finally:
        os.chdir(previous_cwd)


def main() -> int:
    if len(sys.argv) == 5 and sys.argv[1] == "--entrypoint-child":
        result = call_entrypoint(
            pathlib.Path(sys.argv[2]).resolve(),
            sys.argv[3],
            pathlib.Path(sys.argv[4]).resolve(),
        )
        os._exit(result & 0xFF)

    args = parse_args()
    if not args.archive.is_file():
        fail(f"archive does not exist: {args.archive}")

    if args.keep_extracted:
        args.keep_extracted.mkdir(parents=True, exist_ok=True)
        result = run_smoke(args, args.keep_extracted.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="simplegraphic-smoke-") as temp_dir:
            result = run_smoke(args, pathlib.Path(temp_dir).resolve())

    if result is None:
        return 0
    if result != 0:
        fail(f"{args.entrypoint} returned {result}")
    print(f"Smoke-tested {args.archive.name} with {args.entrypoint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
