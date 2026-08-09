# Windows distribution

Run `build.bat` on a 64-bit Windows machine from a Python environment containing
the packages in `client/requirements.txt`. The script never installs packages.

The build uses PyInstaller's one-file, windowed mode and bundles the complete
`client/assets` directory. Outputs are written beneath `dist/` as both an
unpacked release folder and a ZIP archive containing a SHA-256 checksum.

Before PyInstaller starts, `build.bat` runs the local source-secret check
documented in the main client README. A finding stops the build without printing
the detected secret value.

PyInstaller builds are OS-specific. A Windows executable must be produced on
Windows; do not use this script through Wine as a substitute for a clean native
release build.
