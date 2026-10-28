# コーディングエージェント向け

KeyBridgeは、Pi Zero 2 WをWebから操作するUSB HIDキーボード。対象はRaspberry Pi OS Lite 64-bit、Python 3.11以上。

## 実装

- Flaskと素のHTML/CSS/JavaScriptを使い、軽量な構成を保つ。PiでDockerは使わない。
- Web・HID制御・マクロ実行・JSON管理を分離する。対応ファイルは `app/main.py`、`hid_keyboard.py`、`macro_executor.py`、`config_manager.py`。
- 初期対応はUS ASCII。全操作を送信前に検証し、押下後・例外時はキー解放を行う。
- 排他制御はプロセス内ロック。Gunicornは1 workerを維持する。
- 認証・CSRF・アップロード制限を維持する。秘密情報をコード・マクロ・ログへ含めない。
- Webは非rootで動かし、Gadget初期化だけをrootで行う。

## 導入・実機デバッグ

- SCPを基本とし、Pi側のGitは必須にしない。接続例は `pi@hidpi.local`、Webは `http://hidpi.local:8000`。
- 展開先は作業用、インストール先は `/opt/keybridge`。既存のマクロと `/etc/keybridge/keybridge.env` を保持する。
- boot設定の変更はバックアップし、機種条件を考慮する。`[cm5]` のUSB設定をZero 2 Wの競合と扱わない。
- インストールは `Installation complete.` まで確認する。サービス未登録ならインストールの停止箇所を調べる。
- コマンドには開発PC・Piのどちらで実行するか明記する。利用者向け手順は日本語でREADMEへ反映する。

## 検証

Linux・WSL・開発コンテナーで、変更に必要な確認を行う。依存関係は `requirements-dev.txt`。

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
bash -n scripts/*.sh
```

- 不具合修正には必要な回帰テストを追加する。文書のみの変更ではアプリのテストは不要。
- モックでの成功と実機確認を区別する。USB認識・Windows入力・再起動復旧を未確認のまま確認済みと書かない。
- 配布内容を変更したら `bash scripts/package.sh` でSCP用アーカイブを更新する。認証情報・仮想環境・実行時マクロは同梱しない。
