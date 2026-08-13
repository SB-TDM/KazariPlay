# KazariPlay V1.02

ビジュアルノベル（ギャルゲー）ローカルライブラリランチャー · **pywebview（システム WebView）で HTML UI を描画**

旧称 Minato Launcher から、V1.0 より正式に **KazariPlay** へ改名。V1.01 で**コレクションフォルダシステム**を導入、V1.02 で**ゲーム内スクリーンショット通知（C++ Overlay）**と Steam 式スクリーンショット管理を追加。

## 特徴

- **Kawaii Minimal ビジュアル**：UI は HTML/CSS（`kazari_play/ui/web_assets/`）。pywebview + システムの Edge WebView2 で描画
- **ゲーム内スクリーンショット通知（V1.02 新規）**：F12 で撮影後、**ゲーム画面右下**に Steam 式トースト（サムネイル + ゲーム名、下からスライド）を表示。独立した C++ プロセス `overlay.exe`（Direct2D + DirectWrite）で描画し、ゲームウィンドウのみに作用、名前付きパイプでメインプログラムと通信
- **Steam 式スクリーンショット管理**：詳細ページのスクリーンショットカードを左クリックで拡大プレビュー、右クリックでメニュー（名前変更 / ファイルを開く / クリップボードにコピー / 削除）、プレビューはローディングアニメーション付き
- **コレクションシステム（V1.01 新規）**：ツリー型グループ→カテゴリ、ゲームの多対多分類、アコーディオンサイドバー、ドラッグ並び替え、ゲーム管理ダイアログ
- **ゲームライブラリメイン画面**：レスポンシブなカードグリッド、星評価、お気に入りバッジ、実カバー（base64 インライン）
- **詳細ボトムシート（Modal Bottom Sheet）**：カード下部から上にスワイプ、3 列の情報バー、コレクションパスチップ、あらすじ
- **一括選択モード**：カードの円形チェックボックス + 一括ツールバー（全選択/一括追加/一括削除/ライブラリから削除）
- **設定ウィンドウ**：中央モーダル、一般/テーマ（ライブプレビュー）/ショートカット/偽装/アバウト
- 検索 / 並び替え / お気に入り / 続きから遊ぶ ナビゲーション、フレームレスウィンドウ + HTML タイトルバーでドラッグ
- ゲーム起動、プレイ時間の計測、VNDB/Bangumi メタデータマッチングとマルチソース検索
- フロントエンドとバックエンドは **pywebview js_api**（`kazari_play/ui/web_bridge.py`）でブリッジ

## 必要環境

- Python 3.8+
- **Microsoft Edge WebView2 Runtime**（Windows 10/11 には通常内蔵済み。無い場合は winget でインストール）：
  ```bash
  winget install --id Microsoft.EdgeWebView2Runtime -e
  ```

## 実行方法

```bash
pip install -r requirements.txt
python kazari_play/main.py     # KazariPlay_V1.0 ディレクトリ内で実行
```

## C++ Overlay のビルド（任意）

ゲーム内スクリーンショット通知は独立プロセス `overlay/bin/overlay.exe` が提供します。初回実行前にビルドが必要です（MSVC Build Tools、C++ ワークロード必須）：

```bat
cd overlay
build.bat        # 出力：overlay/bin/overlay.exe
```

overlay.exe が無い・ビルド失敗の場合、スクリーンショット通知は自動的に降格します（スクリーンショット本体には影響しません）。

## ディレクトリ構造

```
KazariPlay_V1.0/
├── kazari_play/
│   ├── main.py                # pywebview エントリ（フレームレスウィンドウ + js_api）
│   ├── core/                  # バックエンド中核（スキャン/起動/監視/スクリーンショット/メタデータ/マルチソース/overlay クライアント）
│   ├── database/              # データ層（ゲームライブラリ + コレクション関連テーブル）
│   ├── utils/                 # ユーティリティ（設定/ログ/パス/VNDB/Bangumi）
│   ├── ui/
│   │   ├── web_bridge.py      # pywebview js_api ブリッジ（バックエンドをフロントへ公開）
│   │   └── web_assets/        # index.html + css/ + js/（実 UI）
│   └── resources/
├── overlay/                   # C++ ゲーム内スクリーンショット overlay（Direct2D + 名前付きパイプ IPC）
│   ├── src/                   # main / toast_window / pipe_server / protocol
│   ├── third_party/           # nlohmann/json 単一ヘッダ
│   ├── build.bat              # MSVC ビルドスクリプト
│   └── bin/overlay.exe        # ビルド成果物（git 無視）
├── screenshots/               # スクリーンショット保存（ゲーム別フォルダ、git 無視）
└── tests/
```

## データ

- データベース：`%APPDATA%\KazariPlay\games.db`
- 設定：`%APPDATA%\KazariPlay\config.json`（デフォルトはライト Kawaii テーマ）
- スクリーンショット：`KazariPlay_V1.0/screenshots/{game_id}/`
- 旧版 Minato Launcher からアップグレードする場合、`%APPDATA%\MinatoLauncher` 配下の既存データは自動的に移行されます
