# KazariPlay V1.0

Visual Novel (Galgame) local library launcher · **pywebview (system WebView) rendered HTML UI**

Formerly known as Minato Launcher, officially renamed to **KazariPlay** starting from V1.0.

## Features

- **Kawaii Minimal visual style**: UI is HTML/CSS (`kazari_play/ui/web_assets/`), rendered by pywebview + system Edge WebView2, 100% matching the design mockup
- **Game library main screen**: adaptive card grid, star ratings, favorite badges, real covers (base64 inline)
- **Detail bottom sheet (Modal Bottom Sheet)**: pull up from card bottom, 3-column info bar, tag chips, description
- **Batch select mode**: circular checkboxes on cards + batch toolbar (select all / batch tag / remove tag / move group / remove from library)
- **Tags & categories**: tag management drawer (candy-colored chips, create/delete), category filter
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

## Directory Structure

```
KazariPlay_V1.0/
├── kazari_play/
│   ├── main.py                # pywebview entry (frameless window + js_api)
│   ├── core/                  # backend core (scan/launch/monitor/metadata/multi-source)
│   ├── database/              # data layer (game library + tag/category relations)
│   ├── utils/                 # utilities (config/log/path/safe image loading/VNDB/Bangumi)
│   ├── ui/
│   │   ├── web_bridge.py      # pywebview js_api bridge (exposes backend to frontend)
│   │   └── web_assets/        # index.html + css/ + js/ (actual UI)
│   └── resources/
└── requirements.txt
```

## Data

- Database: `%APPDATA%\KazariPlay\games.db`
- Config: `%APPDATA%\KazariPlay\config.json` (light Kawaii theme by default)
- When upgrading from Minato Launcher, existing data under `%APPDATA%\MinatoLauncher` is migrated automatically
