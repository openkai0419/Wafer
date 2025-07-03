# Combined.spec
# Python 3.10 環境で作成例
main_a = Analysis(['main.py'],
                  pathex=['.'],          # 必要に応じてパス追加
                  binaries=None,
                  datas=[],
                  hiddenimports=[],
                  hookspath=None,
                  runtime_hooks=None,
                  excludes=None)
main_pyz = PYZ(main_a.pure, main_a.zipped_data, cipher=None)
main_exe = EXE(main_pyz, main_a.scripts,
               exclude_binaries=True,
               name='main',        # 実行ファイル名
               debug=False,
               bootloader_ignore_signals=False,
               strip=False,
               upx=True,
               console=False)      # windowed なのでconsole=False

collector_a = Analysis(['collector.py'],
                       pathex=['.'],
                       binaries=None,
                       datas=None,
                       hiddenimports=[],
                       hookspath=None,
                       runtime_hooks=None,
                       excludes=None)
collector_pyz = PYZ(collector_a.pure, collector_a.zipped_data, cipher=None)
collector_exe = EXE(collector_pyz, collector_a.scripts,
                    exclude_binaries=True,
                    name='collector',     # 実行ファイル名
                    debug=False,
                    bootloader_ignore_signals=False,
                    strip=False,
                    upx=True,
                    console=False)

# 共通ライブラリをまとめて一つのフォルダに出力
coll = COLLECT(main_exe,
               collector_exe,
               main_a.binaries,
               collector_a.binaries,
               main_a.zipfiles,
               collector_a.zipfiles,
               main_a.datas,
               collector_a.datas,
               strip=False,
               upx=True,
               name='MyApp')  # フォルダ名
