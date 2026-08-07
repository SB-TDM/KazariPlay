# KazariPlay V1.0

視覺小說（Galgame）本機資料庫啟動器 · **pywebview（系統 WebView）渲染 HTML UI**

原名 Minato Launcher，自 V1.0 起正式更名為 **KazariPlay**。

## 特色

- **Kawaii Minimal 視覺**：UI 為 HTML/CSS（`kazari_play/ui/web_assets/`），由 pywebview + 系統 Edge WebView2 渲染，與設計稿 100% 一致
- **遊戲庫主介面**：自適應卡片網格、星級評分、收藏角標、真實封面（base64 內聯）
- **詳情底部抽屜（Modal Bottom Sheet）**：點擊卡片底部上拉，資訊欄 3 列、標籤 chips、簡介
- **批次選擇模式**：卡片圓形勾選框 + 批次工具列（全選/批次加標籤/移除標籤/移動分組/從庫移除）
- **標籤與分類**：標籤管理抽屜（糖果色 chips、新增/刪除）、分類篩選
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

## 目錄結構

```
KazariPlay_V1.0/
├── kazari_play/
│   ├── main.py                # pywebview 入口（無邊框視窗 + js_api）
│   ├── core/                  # 後端核心（掃描/啟動/監控/元資料/多源搜尋）
│   ├── database/              # 資料層（遊戲庫 + 標籤/分類關聯表）
│   ├── utils/                 # 工具（設定/日誌/路徑/圖片安全載入/VNDB/Bangumi）
│   ├── ui/
│   │   ├── web_bridge.py      # pywebview js_api 橋（後端能力暴露給前端）
│   │   └── web_assets/        # index.html + css/ + js/（真實 UI）
│   └── resources/
└── requirements.txt
```

## 資料

- 資料庫：`%APPDATA%\KazariPlay\games.db`
- 設定：`%APPDATA%\KazariPlay\config.json`（預設淺色 Kawaii 主題）
- 從舊版 Minato Launcher 升級時，`%APPDATA%\MinatoLauncher` 下既有的資料會自動遷移
