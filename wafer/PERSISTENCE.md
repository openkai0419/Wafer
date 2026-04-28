# 永続化レイヤの使い分け

wafer の永続化クラスは「**スコープ**」と「**用途**」の 2 軸で整理されています。
新しい設定値を追加するときは、まず以下の決定木で保存先を決めてください。

## 決定木

```
保存したいデータは…

├─ 1 つの DB に紐づく？  (例: そのDBの parent_folders / ignore_folders)
│   └─ → SettingDB                    (per-DB / SQLite)
│
├─ 1 つのプラグインに閉じる？  (例: WD14 の閾値、ExifTool のブラックリスト)
│   ├─ ユーザーが明示的に保存ボタンで決める設定値？
│   │   └─ → PluginConfig             (per-plugin global / viewer_plugins.ini)
│   │       (収集器に通知が必要なら save_and_notify)
│   └─ 単に「最後の見た目」を覚えるだけ？  (例: パネル内スプリッタ位置、展開状態)
│       └─ → BasePanelPlugin.save_ui_state / restore_ui_state
│           (= StateStore 経由で WindowSlot に格納)
│
├─ コマンドの引数を覚えたい？  (例: rename ダイアログで最後に使ったパターン)
│   └─ → CommandOptionStore           (global / command_options.json)
│
├─ 個別ダイアログのジオメトリ？
│   └─ → DialogLayoutStore            (global / dialog_layout.ini)
│
├─ ウィンドウ単位で違う UI 状態？  (例: フォルダツリーの展開, 検索バー, ズーム)
│   └─ → StateStore.register(...)     (in-memory)
│       → 自動的に WorkspaceStore の WindowSlot に集約される
│
└─ アプリ全体で 1 つの値？  (例: 言語、テーマ、サムネイルサイズ)
    └─ → app_settings (= SettingManager) (global / viewer_settings.ini)
```

## クラス早見表

| クラス | バックエンド | スコープ | 真のオーナー |
|---|---|---|---|
| `SettingManager` (`app_settings`) | INI | App 全体 | アプリ |
| `WorkspaceStore` | JSON | Workspace (複数 WindowSlot) | ワークスペース |
| `StateStore` | (in-memory) | Window | 各コンポーネント。WorkspaceStore に集約 |
| `PluginConfig` | INI section | Plugin (global) | 個別プラグイン |
| `PluginSettings` | INI | App 全体 | プラグインローダ |
| `SettingDB` | SQLite | DB ごと | 個別 DB |
| `CommandOptionStore` | JSON | App 全体 | コマンドシステム |
| `DialogLayoutStore` | INI | Dialog ごと | 個別ダイアログ |
| `ActionGroupStateManager` | (in-memory) | App 全体 | コマンドシステム |

## よくある間違い

- **「最後に開いた DB」を `app_settings` に書かない。** WindowSlot ごとに違うため、`WorkspaceStore.get_last_used_database_name()` から取る。
- **プラグイン設定を `app_settings` に書かない。** プラグインごとに `PluginConfig` を用意する（ai_tagger / florence / exiftool が参考実装）。
- **`StateStore` は永続化しない。** 自分で JSON を書こうとしないこと。`WindowSlot` に渡すだけのインメモリレジストリ。
- **`ActionGroupStateManager` で「現在チェックされている項目」を保持しない。** 状態は UI/データ側が真実で、コマンドの `checked_resolver` 経由で都度問い合わせる。
- **パネルの「設定値」と「UI 状態」を混ぜない。**
  - 設定値（収集器に渡したい、blacklist 等） → `PluginConfig.save_and_notify(...)`
  - UI 状態（スプリッタ・展開・スクロール） → `BasePanelPlugin.save_ui_state / restore_ui_state`
  - `BasePanelPlugin.plugin_config` 属性で「このパネルが所有する PluginConfig」を宣言できる（任意）。

## 参考実装

- パネル設定: [extensions/ai_tagger/panel.py](../extensions/ai_tagger/panel.py), [extensions/florence/panel.py](../extensions/florence/panel.py), [extensions/exiftool/panel.py](../extensions/exiftool/panel.py)
- グリッド/ビューワの UI 状態: [extensions/video/grid.py](../extensions/video/grid.py), [extensions/video/viewer.py](../extensions/video/viewer.py)
- コンポーネントの window-scoped 状態登録: [wafer/app/viewer/mainwindow.py](app/viewer/mainwindow.py) の `_register_*_states`
