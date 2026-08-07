# KazariPlay V1.0

ビジュアルノベル（ギャルゲー）ローカルライブラリランチャー · **pywebview（システム WebView）で HTML UI を描画**

旧称 Minato Launcher から、V1.0 より正式に **KazariPlay** へ改名。

## 特徴

- **Kawaii Minimal ビジュアル**：UI は HTML/CSS（`kazari_play/ui/web_assets/`）。pywebview + システムの Edge WebView2 で描画し、デザイン稿と 100% 一致
- **ゲームライブラリメイン画面**：レスポンシブなカードグリッド、星評価、お気に入りバッジ、実カバー（base64 インライン）
- **詳細ボトムシート（Modal Bottom Sheet）**：カード下部から上にスワイプ、3 列の情報バー、タグチップ、あらすじ
- **一括選択モード**：カードの円形チェックボックス + 一括ツールバー（全選択/一括タグ追加/タグ削除/グループ移動/ライブラリから削除）
- **タグとカテゴリ**：タグ管理ドロワー（キャンディカラーのチップ、作成/削除）、カテゴリ絞り込み
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

## ディレクトリ構造

```
KazariPlay_V1.0/
├── kazari_play/
│   ├── main.py                # pywebview エントリ（フレームレスウィンドウ + js_api）
│   ├── core/                  # バックエンド中核（スキャン/起動/監視/メタデータ/マルチソース）
│   ├── database/              # データ層（ゲームライブラリ + タグ/カテゴリ関連テーブル）
│   ├── utils/                 # ユーティリティ（設定/ログ/パス/画像安全ロード/VNDB/Bangumi）
│   ├── ui/
│   │   ├── web_bridge.py      # pywebview js_api ブリッジ（バックエンドをフロントへ公開）
│   │   └── web_assets/        # index.html + css/ + js/（実 UI）
│   └── resources/
└── requirements.txt
```

## データ

- データベース：`%APPDATA%\KazariPlay\games.db`
- 設定：`%APPDATA%\KazariPlay\config.json`（デフォルトはライト Kawaii テーマ）
- 旧版 Minato Launcher からアップグレードする場合、`%APPDATA%\MinatoLauncher` 配下の既存データは自動的に移行されます
