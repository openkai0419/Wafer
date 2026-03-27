■ このファイルについて
- コードを読むだけでは分からない設計判断、技術的制約、不具合回避のメモ
- ルール（守るべき規約）はrule.txtに記載。ここには書かない
- アーキテクチャ詳細は /memories/repo/*.md に記載。ここでは重複しない

■ テスト保守の注意
- ソース側のクラス名・定数値（NAME, PRIORITY等）を変更したら、対応するテストも必ず同時に更新する
- テストが壊れたまま放置すると、コレクションエラーで全テストが実行できなくなり、フルテストの実行コストが倍増する
- 特にimportレベルのエラー（クラスリネーム等）はpytest全体のコレクションを止めるため影響が大きい

■ ファイル操作の統一設計
- 全ファイル操作はFileExecutor（旧PasteExecutor）を経由する。os.rename()やPath.rename()の直接使用は禁止
- 低レベル関数（_safe_remove, _copy_file等）はプライベート化。外部からの直接呼び出しを防ぐ
- validate_filename()でWindows予約名（CON,NUL等）や不正文字を事前検証。DBメタデータをファイル名に使う箇所は必ず検証を通す
- PasteExecutor/safe_remove/save_remote_itemは後方互換エイリアスとして残存。将来的に削除

■ UI状態の保存/復元の設計思想
- Session（SessionEntry/StateStore）が唯一の状態保存先。app_settings(INI)はグローバル設定（language, cache_size, thumbnail_default_size, tablename）のみ
- コマンドは「操作の実行」のみに責任を持つ。状態保存はStateStore（Session）が担う
- checkable状態の真実のソースはWidget/Pluginの実状態。CommandOptionStoreはメニュー表示用キャッシュ
- StateStoreはwafer/core/に汎用的に定義。wafer側WidgetもPlugin側Widgetも同じ仕組みで参加
- UIState.window_stateにジオメトリ+always_on_topを統合（旧window_geometryは廃止）。WindowStateController.save_full_state/restore_full_stateで一経路化
- WidgetGridPluginのsave_state/restore_stateは_register_grid_plugin_statesでStateStoreに動的登録される（キー: grid_plugin.{name}）
- WidgetViewerPluginのsave_state/restore_stateはfile_viewer._register_statesでStateStoreに動的登録される（キー: viewer_plugin.{name}）
- video/volume, video/muted, tree/state等のセッションスコープ状態はINIから完全移行済み
- VideoGridPlugin.restore_stateはWidget未生成時にMpvCellWidget._pending_grid_stateに保持し、_init_shared時に自動適用する（遅延復元）

■ WidgetViewerPlugin と WidgetGridPlugin のwidget管理の違い
- ViewerPlugin: 1プラグイン=1Widget。__init__でWIDGET_CLASS()から自動生成、self.widgetでアクセス。メソッドにwidget引数不要
- GridPlugin: プール管理で複数Widget。メソッドにwidget引数が必要（どのWidgetか特定できないため）
- PluginRegistry.register()はクラス登録のみ。instance()初回呼び出し時に遅延インスタンス化する
- FileViewerWidget.setup_ui()でviewer_resolver.viewer_plugins()経由でインスタンス取得し、plugin.widgetをstackに追加

■ Dispatcher / Pipeline スレッドモデルの設計思想
目的: アプリ全体のBG処理を「1つの経路」に統一し、独自ワーカークラスやスレッドプール乱立を防ぐ。

● 原則
- メインスレッドはWidget操作のみ。重い処理は全て Dispatcher.post() でBGに投げる
- BGからUI更新が必要な場合は Dispatcher.invoke() でメインに戻す
- キャッシュ操作はBGのまま threading.Lock で排他。invoke()でメインに戻さない
- 独自の QRunnable/QThread/ThreadPool を新たに作らない。全て Dispatcher 経由

● 使うべきクラスと役割
- Dispatcher (wafer/core/qt/dispatcher.py):
  各コンポーネントが Dispatcher(utility_pool) で自前生成。MainWindowから注入ではない。
  post(fn) = BGスレッド実行、invoke(fn) = メインスレッド実行。
  内部でutility_pool（SimpleThreadPool共有シングルトン）を使用。

- CancelToken (wafer/core/qt/dispatcher.py):
  キャンセル用フラグ。set()でキャンセル、is_set()で確認。
  post()のcancel引数に渡すと実行前に自動チェック。

- GridPipeline (wafer/app/viewer/grid/pipeline.py):
  Grid専用のBGタスクスケジューラ。レイアウト計算と可視セルのrender管理。
  dict[int, CancelToken]で可視範囲の差分管理。GridViewはこれに委譲するだけ。
  ImageGridPlugin: BGでplugin.load()→cache→invoke(set_image)。
  WidgetGridPlugin: BGでplugin解決→invokeでメインに戻し_promote_to_widget→plugin.render(widget, path, size)をメインスレッドで呼ぶ。

● コンポーネント別の利用パターン
1. 単発タスク（SearchService, FileViewerWidget, QueryOptions）:
   CancelToken1つ保持 → 新リクエストで前回キャンセル → post(task) → invoke(結果反映)
   Dispatcher直接利用。

2. 多重タスク（FolderTree）:
   dict[key, CancelToken]でノード単位管理 → post(task) → invoke(子ノード追加)
   Dispatcher直接利用。
   _build_roots(), load_children(), add_root()は同期のまま（expand_path連鎖が即時子ノードを前提）。
   on_expanded()のみrequest_expand()経由で非同期化。
   _programmatic_expandカウンターでプログラム的展開中はon_expanded→request_expandを抑制。
   expand_path/set_state/reload_tree等のプログラム的操作と、ユーザーのクリック展開の非同期ロードが競合しないようにする。

3. 大量タスク+プールWidget（Grid）:
   GridPipeline。可視範囲差分でキャンセル/起動を自動管理。

● 新しいBG処理を追加するとき
- QRunnable, QThread, threading.Thread を直接作らない
- CancellableRunnable は廃止済み（thread.pyから削除）。Dispatcher + CancelToken で代替
- Dispatcherをutility_poolで自前生成し、post() + CancelToken で実装する
- UI反映が必要ならinvoke()でメインに戻す
- 変数名規約: CommandContextはctx

● plugin.render() のルール
- WidgetGridPlugin.render(widget, path, size)はメインスレッドで呼ばれる
- ImageGridPlugin: load()のみ実装。BGでの呼び出しとcache→set_imageはPipelineが管理
- WidgetGridPlugin: render(widget, path, size)でWidget操作を直接行う。BGワークが必要ならDispatcher.post()を自分で呼び、完了時にwidget._path != pathでスタルチェック後dispatcher.invoke()でメインに戻す
- appear/disappear/select/deselect/release はメインスレッドで直接呼ばれる（WidgetNotifier経由）
- WidgetNotifier.bind(index, plugin_name) は名前登録のみ。renderは呼ばない（Pipelineの責任）

■ SQLite の罠
- VIEWはマテリアライズされない。ウィンドウ関数入りVIEWをクエリ条件に使うと極端に遅い
- kv_all/kv_metaビューは削除済み。メタデータ取得はmeta_info→tagsの2クエリで行い、同一キーはtagsが勝つ（tags-wins）
- 検索・ソートも直接テーブルアクセス。_kv_sort_joinはCOALESCE(tags, meta_info)でtags-winsを実現
- compound SELECTをFROM句サブクエリにする時、各armを括弧で囲むと構文エラー
- 読み取り専用接続ではcache_size/mmap_sizeのPRAGMAを設定
- IN句のプレースホルダが多すぎるとSQLITE_MAX_VARIABLE_NUMBERを超えてエラー。大量パスのクエリは必ずチャンク分割する（_SQL_CHUNK_SIZE=4000）

■ 動画プレイヤー統合の制約と設計判断
- QOpenGLWidgetはQGraphicsProxyWidgetでは動作しない → viewport子Widget方式を採用
- WIDGET_CLASSを持つプラグインはviewport直接配置（AdditionalWidgetPool管理）
- _sync_additional_widgets()でスクロール・レイアウト変更時にviewport座標へ同期。scrollbar.valueChangedに直接接続（throttle無し）
- Widget判定は_setup_cellでは行わない。常にPixmapItemを作成し、プラグイン解決はGridPipeline BGタスク（_make_resolve_task）で実行。WidgetGridPluginが見つかった場合はinvoke_raw→_promote_to_widgetでメインスレッドに戻す。can_handleはBGで評価されるためメインスレッドを止めない
- GridPipelineが全BGタスク（レイアウト計算・画像ロード・サムネイル取得）を一元管理。Dispatcher.post()でBGスレッド実行、Signal直接emit（AutoConnection→QueuedConnection）でメインスレッド帰還。_deliver_thumbnailのみinvoke()経由
- Pipeline._load_image()がキャッシュチェック→ロード→エラー処理→キャッシュ保存→emit の共通処理を統合。_dispatch_resolve内のImagePluginとfallbackの両方で使う
- animated extensionのWidget（AnimatedCellWidget）は受動的な描画担当。BGデコードはAnimatedGridPlugin._dispatcher（grid_render_pool）で実行。render()でwidget._path=pathを設定後、_decode_and_setをpost。BGでwidget._path!=pathのスタルチェック後、invoke()でメインに戻しset_frames()。_DecodeRunner/_DecodeSignals/_get_thread_pool()は廃止済み
- animated/videoともにREQUIRE_THUMBNAIL=True。サムネイル取得はpipeline側の_dispatch_thumbnailがthumb_dispatcher（thumb pool）に投入。render()内でサムネイルを取得しない。render poolスレッドは即座に開放される
- _dispatch_thumbnailはthumb_dispatcher.post()で非同期投入される。render poolとthumb poolは別プールなので互いにブロックしない
- _deliver_thumbnailはisinstance(widget, plugin.WIDGET_CLASS)ガード付き。BGサムネイル取得中にセルがリサイクルされ別プラグイン型（例: FadePixmapItem）に差し替わった場合、配信をスキップする
- _BaseLayoutCalculatorはQRunnableから通常クラスに変更済み。CalculatorSignals廃止、_resultを直接参照
- _setup_cellはメインスレッドでPixmapItem取得のみ行い、常にpipeline.schedule_render()を呼ぶ。pluginを渡さない場合はBGで遅延解決→WidgetGridPluginならinvokeでメインに戻しpromote→render(widget,path,size)。pluginを渡す場合は直接renderする（リサイズリロード用）
- loader.py（ImageLoaderRunnable/ImageLoaderSignal）は廃止。active_loadersも廃止
- drawForeground()の選択矩形はviewport子Widgetの下に描画される点に注意
- mpv render API (MpvRenderContext) + QOpenGLWidgetでネイティブウィンドウを回避し、Qt描画パイプラインに統合する
- MpvCellWidgetはQWidget（軽量）。サムネイル表示がデフォルト。ホバー時にPlaybackSlotManagerが管理するMpvGLOverlayプール（QOpenGLWidget）を割り当てる
- MpvGLOverlayはMpvCellWidgetの子Widget。activate時にsetParent(cell)で子化し、geometry=(0,0,w,h)で親全体を覆う。viewport()->scroll()による二重移動問題を回避
- PlaybackSlotManagerはN個のselected枠+1個のhover枠+M個のappeared枠を管理。selected超過時はLRU（OrderedDict）で最古を解放。hoverからselectへの昇格、appearedからselectへの昇格にも対応
- MpvGLOverlay._MPV_OPTIONSにmpv生成オプションを集約。_create_player()でMPVインスタンスを生成し、__init__(player=)で外部注入に対応
- PlaybackSlotManagerは_player_poolにmpv.MPVインスタンスを事前生成（PLAYER_POOL_TARGET=2）。Dispatcher(utility_pool)でBGスレッド生成→メインスレッドにinvokeで返却。_acquire()でプール空時に使い、消費後に自動補充。cleanup()で_warm_cancel.set()し未到着分もterminateで安全に解放
- appear/selectは独立したライフサイクル。_appeared_cellsセットで可視状態を追跡し、_appeared辞書でオーバーレイ所有を管理。select時にappearedから昇格（overlay移動）しても_appeared_cellsには残る
- hover activateはデバウンス（200ms）で高速スクロール中の不要なmpv起動を防止
- MpvGLOverlay._ownerで所有MpvCellWidgetを追跡。leaveEventでMpvCellWidget._on_overlay_leave(owner)経由でSlotManagerに通知
- GridView._prev_selection_setで前回選択を追跡し、新規selected/deselectedを差分算出。_ensure_widget_visibleでも復帰時のselect再適用を行う
- サムネイル取得はpipeline._dispatch_thumbnail内の無名タスクでgrid_resolver.load→FileThumbnailerを非同期実行

■ Qt/OpenGL の不具合回避
- QGraphicsOpacityEffectはQOpenGLWidgetに使用禁止。QtがオフスクリーンpixmapにレンダリングしようとしてGLコンテキストが壊れ、映像が表示されなくなる（音声のみ再生される）
- ステールフレーム対策：activate時にGLコンテキスト初期化済み(_ctx存在)ならshow()しない。最初のフレーム到着時に_request_updateでshow。paintGLではawaitingかつframe未到着なら_clear_glで黒クリアし前の動画のフレームをレンダリングしない
- warm_up時のサーフェスタイプ確保はPlaybackSlotManager.__init__でプールに1つMpvGLOverlayを事前生成して行う。遅延生成にするとwarm_upで確保されずウィンドウ再起動が発生する
- ホバー時のマウスイベント：overlayが上に表示されるとcellのleaveEventが発火する場合がある。カーソル位置がoverlay内かチェックして判断。overlay自身のleaveEventで最終的にdeactivateする
- AdditionalWidgetPool.warm_up()でWIDGET_CLASS持ちプラグインのWidgetを事前生成。Window表示前にQOpenGLWidgetを子として持たせることでサーフェスタイプ切り替え（＝Window再起動）を回避

■ プラグインシステムの設計決定経緯
- 旧設計(source+plugins+API仮想モジュール)を廃止し、wafer/を実パッケージ化。旧方式は「制限された客」扱いだった
- wafer.plugin.__init__.pyは「推奨入口」として残す。extensionが必要に応じてwafer.coreやwafer.utilsに直接入ることも許容
- PluginRegistry.registerはNAME重複時に上書き（hotreload対応）
- PluginLoaderのspec_from_file_locationでsubmodule_search_locations=[]を渡すと全サブモジュールがpackage扱いになり相対importが壊れる（別モジュールオブジェクトが生成される）。必ずNone(デフォルト)にすること
- PluginRegistry.resolve()は_ext_cacheで拡張子→プラグインクラスをO(1)解決。register()時にキャッシュ再構築。EXTENSIONS=()のcatch-allプラグインはフォールバック走査
- CollectorResultはdataclass。dict扱いにはto_dict()が必要
- resolverはissubclass(cls,...)の代わりにisinstance(instance,...)を使用
- meta_infoキー衝突回避はプラグイン開発者責任（プレフィックス推奨）
- プラグインのvendor_dirはsys.path.append（標準ライブラリ優先）
- frozen build時はbuild.batでextension依存を.packagesに事前インストール。ユーザー追加extension用にEmbeddedPythonが動的DLで対応
- main.specからpipバンドルを削除済み。frozen buildにpipは不要（EmbeddedPythonが代替）
- BasePlugin.post_install(plugin_dir, on_progress)はpipインストール後のフック。DLLダウンロード等に使う
- BasePlugin.configure()は全プラグインロード後のフック。QSurfaceFormat等に使う。skip_install時も呼ばれる
- MemoryLimitedImageCacheはthreading.Lockでスレッドセーフ化済み
- ViewerResolverはgrid_resolverへの依存をlazy import化。コンストラクタ引数での注入は廃止
- ImageViewerPluginのload_contentはNone返却。ViewerResolverのフォールバック（grid_resolver.load）に委譲

■ DraftOverlayの注意
- _changesと_deletedは明確に分離すること（pop/{}の暗黙ルールでバグ経験あり）

■ 検索フィルタプラグインシステム
- 検索をSearchQuery単一クラスからFilter/Sort/Composerの3層プラグイン構成に分解
- wafer/plugin/query/: base.py(基底), handler.py(レジストリ), builtin.py(TextFilter, DirectoryFilter, 各Sort)
- wafer/plugin/query/composer.py: SearchComposer。filter_entries + sort_plugin → (paths, sources, aspects)
- SearchService: build_filter_entries() + resolve_sort() + _query_snapshot()でdedup
- SearchComposer.list_all_keys(): CTE使用でpath集合を1回だけ評価し、meta_info+tagsからキー列挙
- PluginLoaderの_REGISTRY_MAPにBaseFilterPlugin('filter'), BaseSortPlugin('sort')を追加済み
- SearchQuery/FileSearchEngine.search()はquery.pyに残存。段階的に廃止予定
- 旧テスト(test_query.py 146テスト)はquery.pyのSearchQueryを直接テストしており維持中
- KeyStore (wafer/plugin/query/base.py): DBから取得したkey一覧[(key,count)]を保持する共有オブザーバブル。updated Signalで全購読者に自動配信
- SearchContainerがKeyStoreを所有。FilterRow生成時にkey_storeを注入→_set_filter_typeでcls.bind_key_store(widget, key_store)を呼びシグナル接続+既存データの即時適用
- 新規行追加時もbind_key_store経由で既存データが即座に適用されるため、run_folder_worker再実行不要
- BaseFilterPlugin.bind_key_store()はデフォルトno-op。TextFilterがオーバーライドしてkeys_combo.remakeを接続

■ セッション管理の設計判断
- Trayプロセスも独自QApplicationを持つためInputDialogを表示可能（parent=None）

■ テスト結果の確認方法
- tests/conftest.pyのpytestフック（pytest_configure / pytest_runtest_logreport / pytest_sessionfinish）でtests/test_summary.txtにサマリーを自動書き出し
- 内容: total / passed / failed / skipped / error / exitstatus / duration / カテゴリ別集計 / 失敗テスト一覧+原因
- pyproject.tomlのaddoptsで--tb=short等のオプションを固定済み。コマンドラインでの追加指定は不要

■ AnimatedCellWidget / GridView スクロール最適化の知見
- _sync_additional_widgetでサイズ不変時はmove()のみ使う。setGeometry()はresizeEvent+paintEventを誘発する
- setUpdatesEnabled(False/True)はhide()が大量発生する区間（recycle）には有効だが、move()中心の区間（_sync_additional_widgets）では逆効果。Trueに戻した瞬間にバッチrepaintが発火し、かえってスパイクが増える
- QPixmapの即時破棄（Noneや[]代入）はGDI/GPUリソースの同期解放でメインスレッドを止める。_PixmapDisposerでタイマー分割破棄する
- paintEventでのアップスケール（数ピクセル差）はFrameごとに2-4ms。_decode_framesがjob.sizeでプリスケール済みならアップスケールをスキップし、中央描画でパディングを吸収する
- AnimatedGridPlugin.can_handleはBGスレッド（_make_resolve_task内）で実行されるためUIは止めない。ファイルI/O節約のためキャッシュは有効だがUI直結の最適化ではない
- image.scaled()はFastTransformationで十分。セルサイズ（500px程度）ではSmoothとの視覚差が小さくスクロール時は気づかない

■ checkableコマンドとWidget実状態の同期ルール
CommandOptionStore（永続JSON）はメニューのchecked状態をセッション横断で保持する。
Widget初期化時のデフォルト状態と乖離するため、以下の同期が必須:

● checked状態の読み取り優先順位（_get_checked）
  1. CommandOptionStore（永続JSON）← 前回セッションの古い値が残る
  2. _check_states（実行時メモリ） 
  3. meta.default_checked（コマンド定義）
  → Widget初期化直後にCommand.set_checked()を呼び、1を実状態で上書きする必要がある

● ActionGroup（_get_checked_for_group）
  1. ActionGroupStateManager.get_current() → 未取得時は_load_state()でCommandOptionStoreから遅延読込
  2. group_defaults / meta.default_checked
  → sm.set_current()で実状態を同期する必要がある

● 同期ポイント一覧（Session復元がある場合は上書きされるので安全）
  - MainWindow._sync_default_checked_states(): win.toggle_always_on_top, qry.toggle_include_subfolders/auto_execute, grid action groups, grid_scroll_anchor
  - VideoViewerWidget.__init__(): vview.toggle_mute/fit_mode/loop
  - MpvCellWidget._init_shared(): vgrid.toggle_hover/appear_autoplay（pending stateがない場合のelseブランチ）
  - _sync_service_from_ui() → sync_groups_from_args(): GROUP_SORT/ORDER/MODE/KEYWORD
  - sync_grid_groups_from_settings(): grid_layout_mode, grid_orientation

● 新しいcheckableコマンドを追加する際の注意
  - Widget/Pluginの初期状態とdefault_checkedの値を一致させること
  - Widgetの__init__またはPlugin初期化時にCommand.set_checked()で実状態をCommandOptionStoreに反映すること
  - 怠ると「メニューにチェックが入っているが実際の機能はオフ」のバグが発生する

■ 検索状態管理の注意
- SearchService / ActionGroupStateManager / Session/Bookmark の3系統を同期する必要がある
- Session/Bookmark復元時にsync_groups_from_args()が呼ばれないとActionGroupStateManager状態が不整合になる

■ 存在しないコマンドの実行ハンドリング
- Command.invoke() / Command.run() はコマンドが見つからない場合、ValueErrorをraiseせず AppLogger.warning + Notifier.warning + return None で処理する
- get_args() / set_args() は明示的な設定APIのため、存在しないコマンドに対してはValueErrorをraiseする（従来通り）
- ShortcutManager._exec()はCommand.invoke()のtry-except ValueErrorを維持（他のValueError捕捉用）。コマンド不在のNotifyはinvoke側が担当
- mixins._execute_payload()は独自にhas_command()チェック + Notifier通知済み
- mouse/manager.pyのexecute_drag_start, _handle_dropはcmd_class=None時にNotifier.warning通知する
- _handle_drag_enterはUIゲーティング（ドロップ受入判定）のためNotify不要。cmd不在時はevent.ignore()のみ
- メニュー構築(menu_builder)は存在しないコマンドを警告ログで skip する（メニュー項目を表示しない）
- バインディングJSONは起動時にコマンド存在チェックを行わない（プラグイン再追加の可能性があるため蓄積を許容）

■ その他
- SelectionManager.set_selected(indexes, last)のlastはリスト内位置インデックス
- get_resource_path()はpytest時にCWDフォールバックで_resourcesを解決
- PowerShellで日本語ファイルを編集するとエンコーディング破損する。日本語テキストはcreate_fileツールかPythonで書き換えること

■ テーマシステムの設計方針
- ライト/ダーク対応のため、ハードコード色を廃止しカラートークン方式に移行する
- ThemePalette（frozen dataclass）: bg_*, text_*, accent, accent_text, border_*, success/warning/error/info
- ThemeManager（Singleton）: 現在パレット提供・切替・on_theme_changed Signal通知
- 配置: wafer/core/color/ (theme_palette.py, theme.py, __init__.py)
- extensionはThemeManager.instance().paletteで現在パレットを取得して使用
- 既存ハードコード箇所は段階的にトークン参照へ移行（一括変換不要）
- from_system()でQPaletteから動的生成。is_darkはpalette.bg_primaryの明度で判定

■ カラートークンの使い分けルール
● テキスト系
  - text_primary: 本文テキスト。QPalette.WindowTextから導出
  - text_secondary: 補助テキスト。Dark時はMidlight、Light時はMid
  - text_muted: 薄いテキスト（プレースホルダ等）。PlaceholderTextから導出（WindowTextと近すぎる場合はdarker(160)で補正）
  - text_accent: テキスト上のアクセント色（リンク、カレントセッション名等）。QPalette.LinkまたはHighlightから背景との距離が大きい方を採用
● 背景系
  - bg_primary: メイン背景。QPalette.Window
  - bg_secondary / bg_elevated: セカンダリ背景。QPalette.Base
  - bg_hover / bg_pressed: hover/press時の半透明オーバーレイ
● 差し色（accent）
  - accent: 選択背景、スライダー塗り色、フォーカスリングなど「操作対象」の差し色。常に#3B80FF固定（from_systemでもフォールバック）
  - accent_text: accent背景上で読めるテキスト色。常に#ffffff固定
  - 差し色を使う箇所: FolderTree選択背景、GridView選択矩形、Videoシークバー再生済み部分、Video音量バー、pixmap.pyデフォルトbg_color
● ボーダー系
  - border_default: 標準ボーダー。Dark時はLight(QPalette.Light)、Light時はMid
  - border_subtle: 薄いボーダー
● ステータス系
  - success/warning/error: 状態表示色。dark/lightで固定値
  - info: text_accentと同値

■ ハードコード色の禁止と例外
- 新規コードではThemePaletteのトークンを使うこと。直接#xxxxxxを書かない
- 例外: ThemePalette自体の定義（DARK/LIGHT/from_system内）、QSSのpalette()関数参照

■ アイコンシステム（wafer/core/qt/icon_engine.py）
- _REGISTRYにキー→描画関数(IconDrawFn)を登録。@_register('key')デコレータで追加
- themed_icon(key): QIconEngineベース。描画時にThemeManager.palette.text_primaryで自動着色。Disabledはalpha=80
- icon_draw(key, painter, rect, color): 任意カラーで直接描画。カスタムpaintEvent内で使用（例: _MediaButton）
- padding: themed_icon(padding=0.15)でアイコン領域の内側余白を比率指定（0.0-0.5）
- アイコンはSVG/PNGファイルではなくQPainterPathで描画。解像度非依存
- 新しいアイコン追加時は@_register('key')でicon_engine.pyに描画関数を追加
