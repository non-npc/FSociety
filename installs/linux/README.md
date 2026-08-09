# Linux distribution

Run `sh build.sh` on the Linux architecture being distributed from a Python
environment containing the packages in `client/requirements.txt`. The script
never installs packages. If needed, set `PYTHON_BIN` to the desired interpreter.

The build uses PyInstaller's one-file, windowed mode and bundles the complete
`client/assets` directory. Outputs are written beneath `dist/` as both an
unpacked release folder and a `.tar.gz` archive containing a SHA-256 checksum,
desktop entry, icon, and optional per-user installer.

Before PyInstaller starts, `build.sh` runs the local source-secret check
documented in the main client README. A finding stops the build without printing
the detected secret value.

PyInstaller builds are OS- and architecture-specific. Build separately on each
Linux architecture you intend to distribute. Qt Multimedia playback may also
depend on codecs supplied by the target Linux distribution.
