# KazariPlay V1.02

視覺小說（Galgame）本機資料庫啟動器 · **pywebview（系統 WebView）渲染 HTML UI**

原名 Minato Launcher，自 V1.0 起正式更名為 **KazariPlay**。V1.01 引入**收藏夾資料夾系統**；V1.02 加入**遊戲內截圖提示（C++ Overlay）**與 Steam 式截圖管理。

## 特色

- **Kawaii Minimal 視覺**：UI 為 HTML/CSS（`kazari_play/ui/web_assets/`），由 pywebview + 系統 Edge WebView2 渲染
- **遊戲內截圖提示（V1.02 新增）**：F12 截圖後在**遊戲畫面右下角**彈出 Steam 式 toast（縮圖 + 遊戲名，從底部上滑），由獨立 C++ 程序 `overlay.exe`（Direct2D + DirectWrite）渲染，僅作用於遊戲視窗，與主程序經命名管道通訊
- **Steam 式截圖管理**：詳情頁截圖卡片左鍵放大預覽、右鍵選單（重新命名 / 定位到檔案 / 複製到剪貼簿 / 刪除），預覽視窗附載入動畫
- **收藏夾系統（V1.01 新增）**：樹狀分組→分類、遊戲多對多歸類、手風琴側邊欄、拖曳排序、管理遊戲對話框
- **遊戲庫主介面**：自適應卡片網格、星級評分、收藏角標、真實封面（base64 內聯）
- **詳情底部抽屜（Modal Bottom Sheet）**：點擊卡片底部上拉，資訊欄 3 列、收藏夾路徑 chips、簡介
- **批次選擇模式**：卡片圓形勾選框 + 批次工具列（全選/批次加入收藏夾/批次移除/從庫移除）
- **設定視窗**：置中模態，一般/主題（即時預覽）/快捷鍵/偽裝/關於
- 搜尋 / 排序 / 收藏 / 繼續遊玩 導覽、無邊框視窗 + HTML 標題列拖曳
- 啟動遊戲、遊玩時長統計、VNDB/Bangumi 元資料比對與多源搜尋
- 前後端經 **pywebview js_api**（`kazari_play/ui/web_bridge.py`）橋接

## 前置需求

- Python 3.8+
- **Microsoft Edge WebView2 Runtime**（Windows 10/11 一般已內建；缺少時用 winget 安裝）：
  ```bash
  winget install --id Microsoft.EdgeWebView2Runtime -e
  ```

## 執行

```bash
pip install -r requirements.txt
python kazari_play/main.py     # 在 KazariPlay_V1.0 目錄下
```

## 建置 C++ Overlay（選用）

遊戲內截圖提示由獨立程序 `overlay/bin/overlay.exe` 提供，首次執行前需編譯（需 MSVC Build Tools，含 C++ 工作負載）：

```bat
cd overlay
build.bat        # 產物：overlay/bin/overlay.exe
```

overlay.exe 缺失或編譯失敗時，截圖提示會自動降級（不影響截圖主功能）。

## 目錄結構

```
KazariPlay_V1.0/
├── kazari_play/
│   ├── main.py                # pywebview 入口（無邊框視窗 + js_api）
│   ├── core/                  # 後端核心（掃描/啟動/監控/截圖/元資料/多源搜尋/overlay 客戶端）
│   ├── database/              # 資料層（遊戲庫 + 收藏夾關聯表）
│   ├── utils/                 # 工具（設定/日誌/路徑/VNDB/Bangumi）
│   ├── ui/
│   │   ├── web_bridge.py      # pywebview js_api 橋（後端能力暴露給前端）
│   │   └── web_assets/        # index.html + css/ + js/（真實 UI）
│   └── resources/
├── overlay/                   # C++ 遊戲內截圖 overlay（Direct2D + 命名管道 IPC）
│   ├── src/                   # main / toast_window / pipe_server / protocol
│   ├── third_party/           # nlohmann/json 單頭檔案
│   ├── build.bat              # MSVC 編譯腳本
│   └── bin/overlay.exe        # 編譯產物（git 忽略）
├── screenshots/               # 截圖存放（按遊戲分資料夾，git 忽略）
└── tests/
```

## 資料

- 資料庫：`%APPDATA%\KazariPlay\games.db`
- 設定：`%APPDATA%\KazariPlay\config.json`（預設淺色 Kawaii 主題）
- 截圖：`KazariPlay_V1.0/screenshots/{game_id}/`
- 從舊版 Minato Launcher 升級時，`%APPDATA%\MinatoLauncher` 下既有的資料會自動遷移
