# Path of Building Community SimpleGraphic

## Introduction

`SimpleGraphic` is the native host environment for Lua.
It contains the API used by the application's Lua logic, as well as a
2D OpenGL ES 2.0 renderer, window management, input handling, and a
debug console.
It exports `RunLuaFileAsWin` for compatibility with existing launchers and
`RunLuaFileAsConsole` for platform-neutral launchers. Both are passed a
C-style argc/argv argument list, with the script path as `argv[0]`.

Platform integration is concentrated in a small set of files:
- `win\entry.cpp`: Contains the shared-library exports
It just creates the system main module, and runs it
- `engine\system\win\sys_main.cpp`: The system main module.
It initialises the application, and contains generic OS interface functions,
such as input and clipboard handling
- `engine\system\win\sys_console.cpp`: Manages the Windows debug console window that
appears during the program's initialisation
- `engine\system\win\sys_console_unix.cpp`: Writes the debug console to stderr on POSIX platforms
- `engine\system\win\sys_macos.mm`: Contains macOS-specific URL handling
- `engine\system\win\sys_video.cpp`: Creates and manages the main program window
- `engine\system\win\sys_opengl.cpp`: Initialises OpenGL

## Building

`SimpleGraphic` is built with CMake and vcpkg. Native release artifacts are
packaged by platform and architecture, for example:

* `SimpleGraphicRuntime-win32-x64.tar`
* `SimpleGraphicRuntime-win32-arm64.tar`
* `SimpleGraphicRuntime-macos-arm64.tar`
* `SimpleGraphicRuntime-macos-x64.tar`
* `SimpleGraphicRuntime-linux-arm64.tar`
* `SimpleGraphicRuntime-linux-x64.tar`

The Windows x64 release also keeps publishing the legacy
`SimpleGraphicDLLs-x64-windows.tar` archive for existing consumers.
Release validation writes and publishes `SimpleGraphicRuntime-index.json` beside
the archives so consumers can verify the exact target list, file sizes, and
SHA-256 hashes before installing runtime payloads. The release workflow also
runs the `eagle27272/PathOfBuilding-PoE2` runtime-index verifier against the
artifact set before uploading the index, so the published contract is checked by
the consumer that installs it.
Runtime indexes and release validation accept `SimpleGraphicRuntime` archives
with `.tar`, `.tar.gz`, or `.tgz` suffixes; the package script writes `.tar`
archives by default.
The runtime workflow can also be started manually from GitHub Actions with
`workflow_dispatch` to validate the full pinned runner matrix before a release.
Leave the `runtime_target` input blank to run that matrix. To validate an
experimental target before adding it to the matrix, set `runtime_target`,
`vcpkg_triplet`, and the runner/CMake inputs needed by that host. The custom
workflow lane packages, validates, indexes, smokes, and uploads the single
runtime archive without requiring the legacy Windows compatibility archive. It
also runs the PathOfBuilding-PoE2 runtime-index verifier against the generated
index, so experimental targets prove the same consumer contract before they are
promoted into the release matrix.

To build and package the native runtime for the host machine:

```sh
scripts/package-runtime.sh
```

Set `SIMPLEGRAPHIC_RUNTIME_TARGET` and `SIMPLEGRAPHIC_VCPKG_TRIPLET` to
produce a specific distributable target, such as `macos-arm64` with
`arm64-osx-dynamic`. For future macOS CPU names that CMake supports before this
script has a built-in alias, set `SIMPLEGRAPHIC_CMAKE_OSX_ARCHITECTURES`
explicitly.

Set `SIMPLEGRAPHIC_DRY_RUN=1` to print the resolved runtime target, vcpkg
triplet, CMake generator values, archive path, entry library, and Lua module
names without invoking vcpkg, CMake, or tar. This is useful when adding a new
platform or architecture label to CI.

By default the package script uses the bundled `vcpkg` submodule. Set
`SIMPLEGRAPHIC_VCPKG_ROOT` when packaging inside another host environment, such
as a Linux container using a checkout that already has a macOS or Windows vcpkg
binary in the submodule directory.

For future platforms whose installed shared library or Lua module filenames do
not match the Windows/macOS/Linux defaults, set `SIMPLEGRAPHIC_ENTRY_LIBRARY`,
`SIMPLEGRAPHIC_LUA_MODULE_EXT`, or the per-module overrides
`SIMPLEGRAPHIC_LCURL_MODULE`, `SIMPLEGRAPHIC_LUA_UTF8_MODULE`,
`SIMPLEGRAPHIC_SOCKET_MODULE`, and `SIMPLEGRAPHIC_LZIP_MODULE` before running the
package script. Those values are validated as flat file names and written into
`SimpleGraphicRuntime.json`.
If a future platform has native loader dependencies that should come from the
operating system rather than the archive, set
`SIMPLEGRAPHIC_SYSTEM_DEPENDENCIES` to a comma- or whitespace-separated list of
flat library file names. Declared system dependencies are validated, written into
`SimpleGraphicRuntime.json`, and carried through `SimpleGraphicRuntime-index.json`
for consumers.

Each `SimpleGraphicRuntime-<platform>-<architecture>` archive has a flat root
directory. It contains `SimpleGraphicRuntime.json`, the native
SimpleGraphic shared library (`SimpleGraphic.dll`, `libSimpleGraphic.dylib`, or
`libSimpleGraphic.so` for the supported release platforms), the Lua C modules
(`lcurl`, `socket`, `lua-utf8`, `lzip`), and shared runtime dependencies. The
metadata file records the target, entry library, flat layout, exported entry
points, Lua modules, and the full flat file list owned by the SimpleGraphic
payload. For future platforms outside the current release matrix, the verifier
uses the manifest entry library and module names instead of assuming a new
platform has Linux naming rules. The package script validates the archive
metadata, file ownership list, required Lua modules, the SimpleGraphic entry
exports, every bundled native binary's architecture, and the native loader paths
needed for the archive to remain relocatable after it is installed into a
PathOfBuilding-PoE2 runtime directory. It also rejects macOS metadata sidecar
files and missing bundled library dependencies unless those dependencies are
known platform system libraries or explicitly declared in the archive manifest:

```sh
scripts/verify-runtime-archive.py SimpleGraphicRuntime-macos-arm64.tar
```

To smoke-test that a host-compatible archive can load and execute the
platform-neutral console entrypoint, run:

```sh
scripts/smoke-runtime-archive.py SimpleGraphicRuntime-macos-arm64.tar
```

When validating a cross-built archive on a host with a different CPU
architecture, add `--allow-incompatible-host`; this still extracts and checks
the archive shape, but skips loading the entry library until a matching runner
executes the smoke test.

To write the same machine-readable release index that CI publishes, run:

```sh
scripts/write-runtime-index.py --artifact-dir runtime-artifacts \
  --output runtime-artifacts/SimpleGraphicRuntime-index.json
```

When validating custom artifacts outside GitHub Actions, set
`SIMPLEGRAPHIC_EXPECTED_RUNTIME_TARGETS` to a comma- or space-separated target
list and set `SIMPLEGRAPHIC_REQUIRE_LEGACY_WINDOWS_ARCHIVE=0` if the validation
set does not include the legacy Windows compatibility archive.
Runtime archive names and expected targets are normalized before comparison, so
aliases such as `linux-amd64`, `x64-linux`, and `darwin-aarch64` resolve to the
same canonical targets used by the release index.

The shared library depends on a number of 3rd-party libraries, all provided either as
direct submodules and built by the main `CMakeLists.txt` file or built from
ports in the `vcpkg` submodule as part of the build process.

The build process will also build the `lcurl`, `socket`, `lua-utf8`, and `lzip` Lua extensions
against the same LuaJIT version as the main shared library is built with.

A short guide on building and debugging the shared library is available in
[CONTRIBUTING.md](CONTRIBUTING.md).

The CMake install step deploys only native runtime-loadable files to a flat
installation directory. The release package script clears that install directory
before each install so stale files cannot be captured in the runtime manifest or
archive. This layout is consumed directly by PathOfBuilding-PoE2's native runtime
packager.

On non-macOS POSIX platforms, URL opening defaults to `xdg-open`. Set
`SIMPLEGRAPHIC_OPEN_URL_COMMAND` to the executable name or path for platforms
that use a different desktop URL opener.

## Debugging

Since SimpleGraphic is dynamically loaded by the Path of Building launcher,
debug it by running the launcher for the matching runtime directory and attaching
to that process.

Visual Studio can also be configured to start the Path of Building executable
when debugging a target which troubleshooting of early startup.

## Project dependencies

Runtime and utilities:
* [LuaJIT](https://github.com/LuaJIT/LuaJIT) - fast Lua fork with JIT compilation that has diverged from upstream Lua at version 5.1
* [curl](https://curl.se/) - very common HTTP library, exposed to Lua
* [fmtlib](https://fmt.dev/) - modern string formatting
* [libsodium](https://doc.libsodium.org/) - friendly cryptographic primitives, used in SimpleGraphic for fast hashing
* [pkgconf](http://pkgconf.org/) - part of the build process to locate builds of bundled libraries
* [re2](https://github.com/google/re2) - regex library

Graphics:
* [GLFW](https://www.glfw.org/) - multi-platform windowing library for OpenGL (and other APIs)
* [ANGLE](https://github.com/google/angle) - OpenGL ES runtime from Google built on top of native rendering APIs
* [Glad 2](https://gen.glad.sh/) - OpenGL header generator

Compression and image formats:
* [stb](https://github.com/nothings/stb) - single-header libraries for many things, here image reading and writing
* [giflib](https://sourceforge.net/projects/giflib/) - GIF loading/saving
* [libjpeg-turbo](https://libjpeg-turbo.org/) - JPEG loading/saving
* [libpng](http://www.libpng.org/pub/png/libpng.html) - PNG loading/saving
* [liblzma](https://tukaani.org/xz/) - LZMA compression/decompression
* [zlib](https://www.zlib.net/) - zlib compression/decompression

## Licence

[MIT](https://opensource.org/licenses/MIT)

For 3rd-party licences, see [LICENSE](LICENSE).
The licencing information is considered to be part of the documentation.
