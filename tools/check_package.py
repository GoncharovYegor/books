"""Checks a Linux package (the portable .tar.xz, or a folder it was unpacked to) for libraries it needs but does not ship.

Every shared library that a packaged program or library needs must be in the package's lib/ folder, which start.sh puts on
the library path, or be one that every desktop Linux has (the C library, X11, Wayland, OpenGL, fontconfig, GLib, D-Bus).
A missing one stops the app on a user's machine even though it starts on the build machine (#1415: libicutest.so.74).
Also prints the newest glibc version the package needs, which sets the oldest distribution it runs on.

Usage: python3 tools/check_package.py <package.tar.xz | unpacked folder>
Needs: readelf (binutils).
"""

import fnmatch
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

# Libraries that come with every desktop distribution; the package must not ship them, because they have to match the
# system's drivers and services. Shell patterns on the library file name
SYSTEM_LIBRARIES = [
    # C and C++ runtime: glibc, and the compiler runtime (a newer one ships in lib/compat for older systems)
    "ld-linux-x86-64.so.2", "libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0", "librt.so.1", "libresolv.so.2",
    "libutil.so.1", "libgcc_s.so.1", "libstdc++.so.6",
    # X11, XCB, Wayland and input
    "libX11.so.6", "libX11-xcb.so.1", "libXext.so.6", "libXrender.so.1", "libXi.so.6", "libXfixes.so.3", "libXcursor.so.1",
    "libXrandr.so.2", "libXinerama.so.1", "libSM.so.6", "libICE.so.6", "libxcb*.so.*", "libxkbcommon*.so.0",
    "libwayland-*.so.*",
    # Graphics drivers and fonts
    "libGL.so.1", "libEGL.so.1", "libGLX.so.0", "libOpenGL.so.0", "libgbm.so.1", "libdrm.so.2", "libfontconfig.so.1",
    "libfreetype.so.6", "libharfbuzz.so.0",
    # Desktop services and the GTK theme Qt's platform theme plugin talks to
    "libglib-2.0.so.0", "libgobject-2.0.so.0", "libgio-2.0.so.0", "libgmodule-2.0.so.0", "libgthread-2.0.so.0",
    "libdbus-1.so.3", "libgtk-3.so.0", "libgdk-3.so.0", "libpango-1.0.so.0", "libpangocairo-1.0.so.0", "libcairo.so.2",
    "libcairo-gobject.so.2", "libatk-1.0.so.0", "libgdk_pixbuf-2.0.so.0",
    # Compression, which systemd itself needs
    "libz.so.1", "libzstd.so.1",
]

# Libraries a desktop installation nearly always has, though no package guarantees them: reported, not failed.
# libatomic comes with GCC's runtime but in a package of its own; Qt's Network module links Brotli and Kerberos
USUALLY_PRESENT = ["libatomic.so.1", "libbrotlidec.so.1", "libgssapi_krb5.so.2"]

ELF_MAGIC = b"\x7fELF"


def is_system_library(name: str) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in SYSTEM_LIBRARIES)


def readelf(*args: str) -> str:
    return subprocess.run(["readelf", "-W", *args], check=True, capture_output=True, text=True).stdout


def elf_files(root: Path) -> list[Path]:
    result = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as f:
                if f.read(4) == ELF_MAGIC:
                    result.append(path)
    return result


def needed_libraries(path: Path) -> list[str]:
    return re.findall(r"\(NEEDED\)\s+Shared library: \[([^\]]+)\]", readelf("-d", str(path)))


def glibc_versions(path: Path) -> set[tuple[int, ...]]:
    # Versions this file needs from libc and friends: the "Name: GLIBC_2.34" lines of .gnu.version_r
    return {tuple(int(part) for part in version.split(".")) for version in re.findall(r"Name: GLIBC_([0-9.]+)", readelf("-V", str(path)))}


def check(root: Path) -> int:
    libraries = [folder for folder in root.rglob("lib") if folder.is_dir()]
    if not libraries:
        print(f"no lib folder in {root}")
        return 1
    shipped = {path.name for folder in libraries for path in folder.rglob("*")}

    missing: dict[str, list[str]] = {}
    assumed: dict[str, list[str]] = {}
    newest_glibc: tuple[tuple[int, ...], str] = ((0,), "")
    elves = elf_files(root)
    for path in elves:
        relative = str(path.relative_to(root))
        for name in needed_libraries(path):
            if name in shipped or is_system_library(name):
                continue
            (assumed if name in USUALLY_PRESENT else missing).setdefault(name, []).append(relative)
        for version in glibc_versions(path):
            newest_glibc = max(newest_glibc, (version, relative))

    print(f"{len(elves)} programs and libraries checked")
    if newest_glibc[1]:
        print(f"newest glibc needed: {'.'.join(map(str, newest_glibc[0]))} (by {newest_glibc[1]})")
    for name, users in sorted(assumed.items()):
        print(f"  WARN  {name} is expected on the system, needed by {', '.join(users[:3])}{' and others' if len(users) > 3 else ''}")
    for name, users in sorted(missing.items()):
        print(f"  FAIL  {name} is not in the package, needed by {', '.join(users[:3])}{' and others' if len(users) > 3 else ''}")
    if missing:
        print(f"{len(missing)} needed libraries are missing")
        return 1
    print("every needed library is in the package or part of the system")
    return 0


def main() -> int:
    source = Path(sys.argv[1] if len(sys.argv) > 1 else "")
    if source.is_dir():
        return check(source)
    if not source.is_file():
        print(__doc__)
        return 2
    with tempfile.TemporaryDirectory(prefix="flib-package-") as folder:
        with tarfile.open(source) as archive:
            archive.extractall(folder, filter="data")
        return check(Path(folder))


if __name__ == "__main__":
    sys.exit(main())
