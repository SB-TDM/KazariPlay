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

## Core feature: you pick the folders, it handles the boring part

Choose one or more game folders, and KazariPlay turns a pile of “probably a game” directories into a usable library:

1. **Identify**: scans subfolders and finds the real launch executable — `uninstall.exe` does not get a promotion.
2. **Deduplicate**: checks executable paths and game identity, so moved folders, renamed executables, and rescans do not spawn duplicate cards.
3. **Ask around**: new games are automatically matched against VNDB, Bangumi, Kungal, and other sources — no clicking “match” on every card.
4. **Tidy up**: fills in Chinese titles, descriptions, developers, release dates, playtime, and covers whenever possible.

> When it is not sure, it does not guess silently: automatic matching failures and ambiguous results keep the manual search flow available, with source candidates and per-field selection.

## Features

- **Automatic scan & match (core)**: pick folders, identify launch executables, deduplicate, and pull in metadata from VNDB / Bangumi / Kungal.
- **Manual fallback**: when automatic results are uncertain, search candidates, inspect sources, and apply individual fields yourself.
- **Local library**: search, sorting, ratings, collections, batch actions, and relocation.
- **Network proxy**: follow the system proxy, connect directly, or set a custom HTTP proxy, with a built-in VNDB / Bangumi / Kungal connectivity test.
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
python scripts/package_develop.py --output artifacts/trial-builds/trial-build-1.1.1
```

Output: `artifacts/trial-builds/trial-build-1.1.1/dist/KazariPlay/`. Use `run_develop.cmd`; data stays isolated under the package's `data/`.

</details>

<details>
<summary>Build release assets</summary>

```powershell
python scripts/package_develop.py --output artifacts/trial-builds/trial-build-1.1.1 --release
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

## Acknowledgements

KazariPlay's architecture, interactions, and data organization were informed by the following projects. These are design and implementation references, not direct code reuse; each project's license applies to its own repository.

- [ReinaManager](https://github.com/huoshen80/ReinaManager): source adapters, candidate selection, external ID bridging, rate limiting, and collection structure.
- [PotatoVN](https://github.com/GoldenPotato137/PotatoVN): cover path organization and local image service ideas.
- [LunaTranslator](https://github.com/HIllya51/LunaTranslator): text filtering and experimental translation flow ideas, used only by `feature/hook-translation`.
- [Textractor](https://github.com/Artikash/Textractor): hooking approach reference for the experimental branch; the original build contains neither its code nor binaries.

Thanks also to VNDB, Bangumi, Kungal, and Ymgal for providing public metadata APIs.

## License

GNU General Public License v3.0. See [LICENSE](LICENSE).

Third-party components are listed in [THIRD_PARTY.md](THIRD_PARTY.md).

---

[中文 README](README.md)
