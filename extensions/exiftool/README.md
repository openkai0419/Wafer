## ExifTool Extension

Universal metadata extraction using ExifTool.

### Supported Formats
JPEG, PNG, WebP, BMP, GIF, TIFF, HEIC, HEIF, AVIF, JXL, PSD, ICO, and RAW formats (CR2, CR3, NEF, ARW, ORF, RW2, DNG, RAF, PEF, SRW)

### Features
- **Metadata Collection** — Extracts EXIF/IPTC/XMP data via ExifTool
- **Metadata Panel** — key-value display
- **Settings Panel** — Whitelist/blacklist filtering and deleting

### License

The Python source in this directory is licensed under **LGPL-2.1-or-later** (see the project root `LICENSE`).

This extension downloads and invokes the **ExifTool** command-line application by Phil Harvey at first launch. ExifTool is **not** redistributed in this repository (`lib/` is gitignored).

| Component | Source | License |
|---|---|---|
| ExifTool (`exiftool.exe`) | https://exiftool.org/ | "Same terms as Perl itself" — **Artistic License** or **GPL** (any version). One acceptable choice (GPLv3) is provided in `THIRD_PARTY_LICENSE`. |
| Strawberry Perl runtime (bundled in the Windows ExifTool package) | https://strawberryperl.com/ | See `lib/exiftool_files/Licenses_Strawberry_Perl.zip` after download. |

ExifTool runs as a separate process; only its textual output is consumed. No ExifTool source or object code is statically linked into the extension.
