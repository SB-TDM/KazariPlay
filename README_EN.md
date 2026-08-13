# KazariPlay V1.02

Visual Novel (Galgame) local library launcher · **pywebview (system WebView) rendered HTML UI**

Formerly known as Minato Launcher, officially renamed to **KazariPlay** starting from V1.0. V1.01 introduced the **collection folder system**; V1.02 added **in-game screenshot toast (C++ Overlay)** and Steam-style screenshot management.

## Features

- **Kawaii Minimal visual style**: UI is HTML/CSS (`kazari_play/ui/web_assets/`), rendered by pywebview + system Edge WebView2
- **In-game screenshot toast (new in V1.02)**: after an F12 screenshot, a Steam-style toast (thumbnail + game name, sliding up from the bottom) pops up at the bottom-right of the **game window**, rendered by a standalone C++ process `overlay.exe` (Direct2D + DirectWrite), acting only on the game window and communicating with the main program via named pipe
- **Steam-style screenshot management**: left-click a screenshot card to zoom preview, right-click for a context menu (rename / locate file / copy to clipboard / delete); preview window with loading animation
- **Collection system (new in V1.01)**: tree groups→categories, game many-to-many grouping, accordion sidebar, drag sorting, manage-games dialog
- **Game library main screen**: adaptive card grid, star ratings, favorite badges, real covers (base64 inline)
- **Detail bottom sheet (Modal Bottom Sheet)**: pull up from card bottom, 3-column info bar, collection path chips, description
- **Batch select mode**: circular checkboxes on cards + batch toolbar (select all / batch add / batch remove / remove from library)
- **Settings window**: centered modal, general/theme (live preview)/shortcuts/disguise/about
- Search / sort / favorites / continue playing navigation, frameless window + HTML title bar drag
- Launch games, play-time tracking, VNDB/Bangumi metadata matching & multi-source search
- Frontend/backend bridged via **pywebview js_api** (`kazari_play/ui/web_bridge.py`)

## Requirements

- Python 3.8+
- **Microsoft Edge WebView2 Runtime** (usually built into Windows 10/11; install via winget if missing):
  ```bash
  winget install --id Microsoft.EdgeWebView2Runtime -e
  ```

## Run

```bash
pip install -r requirements.txt
python kazari_play/main.py     # run inside the KazariPlay_V1.0 directory
```

## Build C++ Overlay (optional)

The in-game screenshot toast is provided by a standalone process `overlay/bin/overlay.exe`; compile it before first run (requires MSVC Build Tools with the C++ workload):

```bat
cd overlay
build.bat        # output: overlay/bin/overlay.exe
```

If overlay.exe is missing or fails to build, the screenshot toast silently degrades (the screenshot itself is unaffected).

## Directory Structure

```
KazariPlay_V1.0/
├── kazari_play/
│   ├── main.py                # pywebview entry (frameless window + js_api)
│   ├── core/                  # backend core (scan/launch/monitor/screenshot/metadata/multi-source/overlay client)
│   ├── database/              # data layer (game library + collection relations)
│   ├── utils/                 # utilities (config/log/path/VNDB/Bangumi)
│   ├── ui/
│   │   ├── web_bridge.py      # pywebview js_api bridge (exposes backend to frontend)
│   │   └── web_assets/        # index.html + css/ + js/ (actual UI)
│   └── resources/
├── overlay/                   # C++ in-game screenshot overlay (Direct2D + named pipe IPC)
│   ├── src/                   # main / toast_window / pipe_server / protocol
│   ├── third_party/           # nlohmann/json single header
│   ├── build.bat              # MSVC build script
│   └── bin/overlay.exe        # build output (git-ignored)
├── screenshots/               # screenshot storage (per-game folders, git-ignored)
└── tests/
```

## Data

- Database: `%APPDATA%\KazariPlay\games.db`
- Config: `%APPDATA%\KazariPlay\config.json` (light Kawaii theme by default)
- Screenshots: `KazariPlay_V1.0/screenshots/{game_id}/`
- When upgrading from Minato Launcher, existing data under `%APPDATA%\MinatoLauncher` is migrated automatically
