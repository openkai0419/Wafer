# mpv PoC - 動画再生プラグイン検証

## セットアップ手順

### 1. libmpv DLLの取得
https://sourceforge.net/projects/mpv-player-windows/files/libmpv/
から `mpv-dev-x86_64-*.7z` をダウンロードし、中の `mpv-2.dll` をこのディレクトリに配置。

または、mpv公式ビルド https://mpv.io/installation/ からmpvをインストールし、
インストールディレクトリ内の `mpv-2.dll` をコピー。

### 2. 動作確認
```
python prototypes/mpv_poc/test_dll.py
```

### 3. PySide6埋め込みテスト
```
python prototypes/mpv_poc/test_embed.py
```
