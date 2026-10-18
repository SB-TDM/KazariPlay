<p align="center">
  <img src="docs/design/logo.png" width="160" alt="KazariPlay logo">
</p>

<h1 align="center">KazariPlay</h1>

<p align="center">
  A local visual novel library launcher for Windows: scan, organize, match metadata, take screenshots, and stay updated.
</p>

<p align="center">
  <a href="https://github.com/SB-TDM/KazariPlay/releases/latest">
    <img alt="Release" src="https://img.shields.io/github/v/release/SB-TDM/KazariPlay?label=release">
  </a>
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-0078D4">
  <a href="LICENSE">
    <img alt="License" src="https://img.shields.io/github/license/SB-TDM/KazariPlay">
  </a>
</p>

<p align="center">
  <a href="https://github.com/SB-TDM/KazariPlay/releases/latest">
    <img alt="Download latest release" src="https://img.shields.io/badge/download-latest-2ea44f?style=for-the-badge">
  </a>
</p>

KazariPlay manages a local visual novel (Galgame) library without tying it to a specific launcher. It scans folders, presents games as cards, and matches metadata from VNDB, Bangumi, Kungal, and other sources.

> This is the original, non-translation build. Translation, hook injection, and AI subtitle experiments live in `feature/hook-translation`.

## Features

- **Local library**: folder scanning, executable detection, deduplication, search, sorting, ratings, and favorites.
- **Multi-source metadata**: parallel VNDB / Bangumi / Kungal / Ymgal search with Chinese titles, Japanese original titles, and external ID bridging.
- **Screenshots**: F12 capture with WGC / PrintWindow / fullscreen fallback and an in-game Steam-style toast.
- **Collections and batch actions**: tree collections, batch assignment, removal, and relocation.
- **Auto updates**: GitHub Releases checks, downloads, SHA256 verification, data backup, and rollback on failure.
- **Native Windows UI**: frameless window, local cover HTTP service, and system WebView2 rendering.

## Download

Download the latest `KazariPlay-win64.zip` from [Releases](https://github.com/SB-TDM/KazariPlay/releases/latest).

1. Extract to a writable directory outside system folders.
2. Run `KazariPlay.exe`.
3. Scan your game folders on first launch.

Do not place it under `Program Files` or another location that requires administrator rights. Microsoft Edge WebView2 Runtime is required and is usually included with Windows 10/11.

## Data

| Data | Default location |
|---|---|
| Database | `%APPDATA%\KazariPlay\games.db` |
| Config | `%APPDATA%\KazariPlay\config.json` |
| Logs | `%APPDATA%\KazariPlay\logs\` |
| Covers | `%APPDATA%\KazariPlay\covers\` |
| Screenshots | `screenshots/` under the app directory or `KAZARIPLAY_DATA_DIR` |

Back up `%APPDATA%\KazariPlay` before upgrading or reinstalling. Legacy Minato Launcher data is migrated on first launch when available.

## Run from source

Requires Python 3.11, Node.js/npm, and WebView2.

```bash
pip install -r requirements.txt
npm --prefix src/kazari_play/ui/web_assets ci
npm --prefix src/kazari_play/ui/web_assets run build
python src/kazari_play/main.py
```

<details>
<summary>Build a local test package</summary>

```powershell
python scripts/package_develop.py --output artifacts/trial-builds/trial-build-1.1.0
```

Output: `artifacts/trial-builds/trial-build-1.1.0/dist/KazariPlay/`. Use `run_develop.cmd`; data stays isolated under the package's `data/`.

</details>

<details>
<summary>Build release assets</summary>

```powershell
python scripts/package_develop.py --output artifacts/trial-builds/trial-build-1.1.0 --release
```

This produces `KazariPlay-win64.zip` and `SHA256SUMS.txt` and requires a clean worktree.

</details>

## Tech stack

- Python 3.11 + pywebview 6 + SQLite
- TypeScript frontend compiled to classic scripts
- Windows Graphics Capture / PrintWindow screenshots
- C++ overlay (Direct2D + named-pipe IPC)
- PyInstaller onedir packaging

## Development

- [Architecture](docs/ARCHITECTURE.md)
- [Backend modules](docs/backend/README.md)
- [Frontend modules](docs/frontend/README.md)
- [Development rules](docs/dev/DEV_RULES.md)
- [Testing](docs/dev/testing.md)
- [Changelog](docs/dev/CHANGELOG.md)
- [Branch workflow](docs/dev/BRANCH_WORKFLOW.md)

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).

Third-party components are listed in [THIRD_PARTY.md](THIRD_PARTY.md).

---

[中文 README](README.md)
