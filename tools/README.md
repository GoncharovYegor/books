# Developer tools

Run from the repository root.

| Tool | What it does | Usage |
|---|---|---|
| `check_exported_symbols.py` | Fails if one of our binaries exports a third-party library (libpng, freetype, libjpeg, libxml2...). Such exports crash GTK's file dialog and break JPEG loading. | `python3 tools/check_exported_symbols.py build` |
| `find_contextless_timers.py` | Lists `QTimer::singleShot` lambdas without a context object, which can run after their object is destroyed. | `python3 tools/find_contextless_timers.py src` |
| `scan_style.py` | Naming and formatting metrics: long lines, BOMs, file and folder name case, `m_` members, misspellings. | `python3 tools/scan_style.py src/home` |
| `scan_design.py` | Design metrics: injected dependencies per constructor, single-implementation interfaces, embedded SQL, shared-library count. | `python3 tools/scan_design.py .` |
| `run_sanitizers.sh` | Runs the HTTP, start-up and GUI suites on a sanitizer build and collects the AddressSanitizer, UBSan and ThreadSanitizer reports. Suppressions for third-party code are in `sanitizers/`. | `tools/run_sanitizers.sh build-asan` |

## Sanitizer builds

Each sanitizer gets its own Debug build folder, next to `build-debug`. The Conan dependencies are the Debug ones, so a
configure reuses them. Only our code is instrumented; Qt and the Conan libraries are not, which is why ThreadSanitizer
needs the suppressions in `sanitizers/tsan.supp`. Build with few jobs: a sanitized compile needs about twice the memory.

```
cmake -S . -B build-asan -G Ninja -DCMAKE_BUILD_TYPE=Debug -DFLIBRARY_SANITIZE=address,undefined -DQt6_DIR=... -D7zip_BIN_DIR=... -DNPM_EXECUTABLE=$(which npm)
cmake -S . -B build-tsan -G Ninja -DCMAKE_BUILD_TYPE=Debug -DFLIBRARY_SANITIZE=thread -DQt6_DIR=... -D7zip_BIN_DIR=... -DNPM_EXECUTABLE=$(which npm)
cmake --build build-asan -j3
tools/run_sanitizers.sh build-asan
```

The sanitizer builds keep compiler warnings as warnings: GCC reports false `maybe-uninitialized` and `stringop` warnings
in libstdc++ code once it is instrumented. In a UBSan build `logic` links Qt Widgets too: the `vptr` check needs the type
information of the dialogs it calls, and `opds` would not link otherwise.

GCC 14's ThreadSanitizer stops with "unexpected memory mapping" under the address randomisation of 6.x kernels.
`run_sanitizers.sh` runs everything under `setarch -R`; to start a TSan program by hand, do the same:
`setarch $(uname -m) -R build-tsan/bin/opds ...`.

## Reproducers (`repro/`)

Small programs that load FLibrary's libraries into a process the way the app does, to show symbol clashes without the GUI.
Build them against the Debug or Release `lib/` folder. Set `QT_PREFIX` to your Qt installation (the folder that contains
`lib/cmake/Qt6`):

```
Q=$QT_PREFIX; L=$PWD/build/lib
g++-14 -std=c++17 -fPIC tools/repro/dialog_repro.cpp -I$Q/include -I$Q/include/QtWidgets -I$Q/include/QtGui -I$Q/include/QtCore \
    -o /tmp/dialog_repro -L$Q/lib -Wl,-rpath,$Q/lib -lQt6Widgets -lQt6Gui -lQt6Core \
    -Wl,--no-as-needed $L/libflipdf.so $L/libutil.so $L/libfljxl.so $L/libdjvulibre.so -Wl,-rpath,$L
QT_QPA_PLATFORMTHEME=gtk3 xvfb-run -a /tmp/dialog_repro      # native folder dialog: must stay up 4 s, exit 0

gcc-14 -std=c11 tools/repro/pixbuf_repro.c -o /tmp/pixbuf_repro -ldl -Wl,--no-as-needed $L/libdjvulibre.so -Wl,-rpath,$L
/tmp/pixbuf_repro some.jpg                                    # system JPEG loader: must print "loaded"
```

`jpeg_repro.cpp` does the same through Qt's own JPEG plugin (build like `dialog_repro.cpp`, linking `Qt6Gui` and `Qt6Core`).
