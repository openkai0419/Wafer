■ このファイルについて
- 設計上・思想上の絶対ルール。違反するとバグや設計崩壊を招く項目のみ記載
- copilot-instructions.md に記載済みの一般ルールは書かない
- 実装前に必ず確認し、実装後にルールに反する変更がないか検証する

■ dpix() の適用ルール
- ウィジェットサイズ、icon.pixmap、setContentsMargins、setSpacing等 → dpix()必須
- スタイルシート内のpx値もdpix()でf-string化
- QSizeデフォルト引数はNone→関数内でdpix()解決
- 除外: QGraphicsScene内シーン座標、QPixmap内描画座標、0px、1px極小ボーダー

■ 例外処理
- error()はログのみ。raiseは呼び出し側が明示的に行う
- 元の例外型を保持（RuntimeErrorへの変換禁止）。raise from exc を使う
- try/exceptの代わりに型・存在確認で安全に動かすことを基本とする
- ctx.get_instance/pos等の前提崩壊時はコマンド側で握りつぶさず例外で落とす

■ コマンド設計
- 汎用コマンドはevent非依存。キー/マウス/メニュー/別Widget全経路で動作すること
- Command.runのargsは一時的。get_args/set_argsと独立
- UI関連を直接操作するコマンドの場合、状態の真実のソースはWidget/Pluginの実状態。コマンド関数内で状態変更したら必ずCommand.set_checked()でメニュー表示を同期する。
- コマンドは"UI/設定をその値に変更する"責任のみを負う。再起動時に再現する等、実態の保存と再現はStateやOption等の別の設定を利用すること。
- action_groupのIDはコマンドのpath末尾と完全一致。表示用ラベルを含めない
- シングルトン: actions以下は全てinstance()パターンに統一。__new__やdict pattern禁止。テストでは_instance=Noneでリセット
- CommandOptionStore.configure()はinstance()前に必ず呼ぶ。テストではtmp_pathで初期化し、finally内で_instance/_default_pathを復元
- re-exportだけのファイル(ui.py等)は作らず実モジュールから直接importさせる
- KeyCombo/KeyChordSpec等の型エイリアスもcombo.pyに一元化
- modifier_keys_from_qt()でQt修飾キー→Key_*変換を一元管理（combo.py）
- @require デコレータ（wafer.core.commands.command.require）でインスタンス注入。@require_v でctx.get()値注入。Ctxクラスは廃止
- path/pathsのようなフォールバックロジックがあるctx値は補助関数（_ctx_path等）で関数内から直接呼ぶ。デコレータ化しない
- CommandMeta.priorityフィールドで同一IDの上書き優先度を制御（高い方が勝つ、同値は後勝ち）

■ メニュー/バインディング
- ホットキー解決は_resolve_hotkeys_batchでバッチ取得。ループ内個別呼出禁止
- CommandMenuRowのdpix値はクラスレベルキャッシュ(_px)で再利用
- findChildはコスト高。保持済み属性参照を使う
- actions以下のバインディング周りのクラス、コマンドを外部から使う場合は必ずbridgeを経由
- コマンド実行の責任統一: stored args解決とrequiredチェックはCommand.invoke()に集約。メニュー/キーバインドはctxを構築してCommand.invoke()に委譲

■ GridView (QGraphicsView)
- index_at_pos()はView座標を受取り、内部でmapToScene()変換
- rect_selectの座標はto_scene_pos()でScene座標に変換して保存
- scene.setSceneRect()でスクロール範囲を制御

■ プラグインインターフェース規約
- WidgetViewerPlugin.render(widget, path)とWidgetGridPlugin.render(widget, path, size)で引数順を統一。操作対象のwidgetが先。どちらもメインスレッドで呼ばれる
- WidgetViewerPlugin.clear(widget)とWidgetGridPlugin.release(widget)は異なるセマンティクス（clear=コンテンツリセット、release=リソース解放）のため名前は別
- BaseGridPlugin.release(widget)は画面外スクロール時にAdditionalWidgetPoolから呼ばれる。GPUリソース等重い資源はsuspend/resume方式。cleanup()は完全破壊のみ
- Grid/ViewerのWIDGET_CLASSとload()は排他。Widget生成はシステム管理
- Collectorはmeta_info+statusのみ返す。name/aspect/file_hashはPhase1で設定
- PRIORITY大=高優先。EXTENSIONS=()は全ファイルマッチ
- render(widget, path, size)は戻り値なし。フォールバックはresolve_chain内のcan_handle()で制御。BGワークが必要なプラグインはDispatcher.post()を自分で呼ぶ
- BaseGridPlugin.select(widget, path) / deselect(widget)はGridResolverがGridView._on_selection_changed内の差分計算で呼び出す
- プラグインのGrid/View/Commandは個別に登録・登録解除できる設計を前提とする
- 汎用的な機能をプラグイン専用のインターフェースで提供しない。wafer側でも使う仕組みはwafer側に汎用的に定義し、プラグイン基底クラスはそれを利用する形にする
- コマンドはctx経由で取得し、UIがコマンド状態を参照する時はコマンド不在を考慮する
- プラグインが読み込まれていなくてもアプリが落ちないこと（直接importしたファイル不在はエラーで可）

■ ビルトインとExtensionの二層構成
- ビルトイン実装はwafer/builtins/に配置。extensionと同じプラグインインターフェースを使う
- extensions/はPluginLoaderが外部ディレクトリから自動検出。wafer/builtins/はload_plugins()内でregister_all()により登録
- ビルトインとextensionの唯一の違いはexe化時にwafer/builtins/は自動的に同梱される点。設計・インターフェースは同一
- Grid/Viewerのフォールバックはビルトインプラグイン（EXTENSIONS=(), PRIORITY=-100）として登録。Resolverにフォールバックロジックをハードコードしない
- Filter/Sortのビルトイン実装もwafer/builtins/filters.py, sorts.pyに配置。wafer/plugin/query/builtin.pyはre-export用の互換レイヤー
- コマンドはCommandMeta/ActionKit系で別体系のためbuiltinsに含めない。wafer/app/以下とextensions/に分散するのが正しい

■ 未登録コマンドへの安全なフォールバック
- CommandRegistry.execute()は未登録コマンドでNone返却+warning。ValueErrorは投げない
- CommandMenuBuilder.build_into()は未知コマンドIDをスキップ（warningログ）
- バインディング実行時（mixins/ShortcutManager）は未登録コマンドをNotifier.warningでユーザー通知
- bridge.pyのCommand.get_checked()は未登録コマンドでFalse返却。MenuSpec.exec()はbuild失敗でNone返却

■ プラグインローダー規約
- extensionsはwafer.plugin（公開API）、wafer.utils、wafer.coreを直接import可能。wafer.appへの依存は非推奨
- wafer.plugin.__init__.pyがextension向け公開API。AppLoggerやprofilerは公開APIに含めない（extensionはwafer.utilsから直接import）
- extension側のMenuGroupはPluginLoader._deferred_commandsに一時保持し、register_extension_commands()でMainWindow/viewer commandsの後に登録
- MenuGroup.PRIORITYでAllMenuのルート表示順を制御。昇順ソート。viewer標準は10刻み(10-110)、extensionは1000台を推奨
- extension側のMenuGroupはGrid/View別に分離する（例: VideoGridCommands, 将来のVideoViewCommands）
- frozen環境でのpip実行にはEmbeddedPython使用。pip._internal直呼出は禁止
- setup_menu()ではSettings.configure()をコマンド登録より先に実行する
- _setup_dll_directoryは_load_oneで初回呼出+post_install後に再呼出の2箇所。両方必要

■ プロトタイプの方針
- プロトタイプは完全な状態まで持っていき、そのままメイン側に統合できる品質にする
- 複雑なOSレベルのハック（Win32 ColorKey透過等）はプロトタイプに不適。シンプルで強力な設計を選ぶ
- テスト中に本番の統合先（GridView、OverlayStack等）との互換性も検証する

■ セッション管理
- 匿名セッションは廃止。全ウィンドウは必ず名前付きセッション
- デフォルト名はDEFAULT_SESSION_NAME("Wafer")。連番は1始まり
- セッション管理コマンドはSessionCommandsを廃止しWindowCommandsに統合
- CommandParamにchoices_fn(callable value)とrequiredを追加。required未充足時はCommandOptionsDialogを自動表示

■ テスト環境
- tests/conftest.pyでload_plugins(skip_install=True)を呼んでextensionレジストリを初期化する
- extensionのvendored numpy（.packages/numpy）がsys.modulesを汚染する。conftest.pyでプラグインロード後にnumpy関連モジュールをsys.modulesから除去すること
- Qtウィジェットテストでスクロールバー表示等によるviewportリサイズを検証する場合はshow()を呼んでから検証する
- IPCテストはtests/wafer/core/ipc/conftest.pyで_PORT_FILEをtmp_pathに隔離
- GridViewを実インスタンス化するテスト（show()やprocessEvents()を使う場合）はCommandOptionStore.configure()をmodule-scoped fixtureで初期化する
- SearchQuery.__post_init__はlist引数をtupleに変換する。テストでは比較もtupleで行う
- テストの重複ファイル・重複メソッド名に注意。Pythonは同名メソッドを後勝ちで上書きし、pytestは1つしか収集しない
- conftest.pyのpytest_sessionfinishフックでテスト結果を.temp/test_summary.txtに自動書き出し。テスト実行後はターミナル出力ではなくこのファイルを読んで結果を確認すること
- pyproject.tomlのtimeout=30で各テスト30秒タイムアウト（pytest-timeout）。不要なプロセス残留を防止

■ テスト用データセット (.sample/)
- dataset_downloader.pyは目視デバッグ・ストレステスト用。自動テストは自前でPIL画像を生成する
- 新しいextensionを追加したらdataset_downloader.pyにもそのファイル形式の生成/DLを追加する
- 対応するextensionが存在しないファイル形式（audio, archive等）はdataset_downloaderに含めない
- .sample/coco/ は手動DL専用ディレクトリ。statusコマンドで検出・表示するがmanifest管理はしない
- Picsumの利用可能IDリストは_picsum_ids.jsonにキャッシュ。ユニークID優先で重複を最小化する
