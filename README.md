# KeyBridge

Raspberry Pi Zero 2 Wを、Wi-Fiから操作できるUSB HIDキーボードにします。
スマートフォンなどのWeb画面でボタンを押すと、登録した文字列やキー操作をUSB接続先へ送信します。
Windows側に専用ソフトは不要です。**現在キーボードフォーカスのあるアプリ**へ入力されます。

Python / Flask / HTML・CSS・JavaScript / Linux ConfigFSを使用します。Dockerやフロントエンドのビルドは不要です。

## 対応条件と確認状況

- Raspberry Pi Zero 2 W、Raspberry Pi OS Lite **64-bit**、Python **3.11以上**。
- Wi-FiとUSB**データ通信対応**のmicro USBケーブル。**USB** と表示された端子をWindowsに接続します。**PWR IN** 端子ではHID通信できません。
- 接続先は**US配列、IMEオフ、Caps Lockオフ**を前提とします。WindowsがJIS配列として扱う場合は記号が一致しません。
- 操作画面はUSB接続先とは**別のスマートフォンやPC**で開きます。同じPCではブラウザへフォーカスが移るためです。
- 初回インストールには、PiからaptとPyPIへアクセスできるネットワークが必要です。
- **実機動作は未確認です。** ローカルではHID I/Oをモック化して検証しています。USB列挙、Windows上の入力、Pi再起動時の復旧は後述の実機チェックで確認してください。

```text
スマートフォン / 操作用PC
       │ Wi-Fi・HTTP + Basic認証
       ▼
Pi Zero 2 W: Flask → マクロ実行 → /dev/hidg0 → USB → Windowsの入力先アプリ
```

## Piの準備

1. [Raspberry Pi Imager](https://www.raspberrypi.com/software/)でmicroSDへRaspberry Pi OS Lite (64-bit)を書き込みます。
2. Imagerのカスタマイズでホスト名（例: `hidpi`）、管理ユーザー（例: `pi`）、Wi-FiのSSID・パスワード・国、SSHを設定します。SSH公開鍵認証を推奨します。Web用ユーザーは後で別途設定します。
3. Piを起動し、同じLANから `ssh pi@hidpi.local` で接続します。`pi` と `hidpi` は実際の管理ユーザー名・ホスト名に置き換えてください。名前解決できない場合はルーターなどで調べたIPを使用します。

詳しくは[Raspberry Pi公式の初期設定ガイド](https://www.raspberrypi.com/documentation/computers/getting-started.html)を参照してください。

## SCPでインストール（推奨）

開発PCで、このリポジトリのルートから配布アーカイブを作成します。VS Code開発コンテナー、Linux、WSL、Git Bashなどで実行できます。

```bash
bash scripts/package.sh
scp dist/keybridge.tar.gz pi@hidpi.local:~/keybridge.tar.gz
ssh pi@hidpi.local
```

Windows PowerShellだけで梱包する場合（リポジトリのルートで実行）:

```powershell
tar -czf keybridge.tar.gz app data/macros.example.json scripts systemd tests requirements.txt requirements-dev.txt pyproject.toml README.md LICENSE
scp keybridge.tar.gz pi@hidpi.local:~/keybridge.tar.gz
ssh pi@hidpi.local
```

**以下はSSH接続したPi上で実行します。** 空の展開先を作り、インストールします。

```bash
upload_dir=$(mktemp -d "$HOME/keybridge-upload.XXXXXX")
tar -xzf ~/keybridge.tar.gz -C "$upload_dir"
cd "$upload_dir"
sudo bash scripts/install.sh
sudo reboot
```

再起動後は、下の[再起動後に最初の入力を試す](#再起動後に最初の入力を試す)へ進んでください。

Web用ユーザー名と12文字以上のパスワードを対話式で設定します。パスワードはコマンドラインやログへ出しません。
Pi側にGitは不要です。PCの仮想環境はコピーせず、Pi上で作成します。インストーラーはPiのモデルを確認するため、開発PC上では実行できません。
再起動前に、インストーラーの最後に **`Installation complete.`** が表示されたことを確認してください。エラーで止まった場合は、その原因を解消してから再実行します。

GitHub経由ならPi上でリポジトリを取得し、同じインストーラーを使います。`REPOSITORY_URL` を実際のURLへ置き換えてください。

```bash
sudo apt-get update
sudo apt-get install -y git
git clone REPOSITORY_URL keybridge-upload
cd keybridge-upload
sudo bash scripts/install.sh
sudo reboot
```

## 再起動後に最初の入力を試す

`install.sh` と再起動が終わったら、次の順に操作してください。アプリはsystemdで自動起動する設定になっています。

1. **PiをWindowsへUSB接続します。** Piの **USB** と表示された端子を、データ通信対応ケーブルでWindowsへ接続してください。**PWR IN** 端子ではキー入力を送れません。
2. **Windowsでメモ帳を開きます。** 本文の入力欄をクリックして、カーソルを置いてください。
3. **別のスマートフォンやPCで操作画面を開きます。** Piと同じWi-Fi/LANに接続し、ブラウザで **`http://hidpi.local:8000`** を開いてください。Windowsのメモ帳にはフォーカスを置いたままにします。
4. **Web用の認証情報を入力します。** `install.sh` 実行中に設定したWeb用ユーザー名・パスワードを使います。ユーザー名の質問で何も入力しなかった場合は `keybridge` です。
5. **「Hello World」を押します。** 画面に「USB接続済み」が表示されていることを確認してボタンを押し、Windowsのメモ帳に `Hello World!` が入力されれば最初の動作確認は完了です。

### 操作画面が開かない場合

下の[Webにアクセスできないときの確認](#webにアクセスできないときの確認)を順番に実行してください。サービス・ポート・HTTP応答・操作端末からの接続を切り分けます。

### 次に自分の定型文を登録する

最初の入力を確認できたら、[JSON形式](#json形式)に従って設定ファイルを作成し、Web画面の「JSONをインポート」から読み込んでください。現在の設定は「エクスポート」で保存できます。

## Webにアクセスできないときの確認

まず **Pi自身でWebサーバーが動いているか** を確認し、その後で操作端末との通信を確認します。USBが未接続でも、Web画面にはアクセスできる設計です。

### 1. PiへSSH接続してIPアドレスを確認する

**操作用PCで実行:**

```bash
ssh pi@hidpi.local
```

SSHでも名前が見つからない場合は、ルーターの接続端末一覧などでPiのIPを調べ、`ssh pi@そのIP` で接続してください。

**SSH接続後、Pi上で実行:**

```bash
hostname -I
ip -br -4 addr show wlan0
```

`wlan0` に割り当てられたIPv4アドレスを使います。複数表示された場合、`127.0.0.1` は操作端末からの接続には使いません。
以降の `192.168.1.50` は例です。**実際に表示されたPiのIPへ置き換えてください。**
Wi-FiのIPがなければ、先にPiのWi-Fi設定・接続を確認します。

### 2. Webサービスの状態とログを確認する

**Pi上で実行:**

```bash
sudo systemctl status keybridge-web keybridge-gadget --no-pager -l
sudo journalctl -u keybridge-web -u keybridge-gadget -b -n 100 --no-pager
```

| 表示 | 意味・次の確認 |
| --- | --- |
| Webが `active (running)` | 起動中。次のポート確認へ進む |
| Webが `failed` / `activating (auto-restart)` | 起動失敗や再起動の繰り返し。journalの末尾だけでなく、直前の例外・エラーを確認 |
| Webが `inactive (dead)` | 停止中。下の起動コマンドを実行し、もう一度状態・ログを確認 |
| `Unit ... could not be found` | サービスが未登録。インストールが最後まで完了したか確認 |
| Gadgetが `active (exited)` | oneshotによる初期化完了。これは正常 |

**サービスが見つからない場合:** ポート確認へ進む前に、Pi上でインストールの状態を確認します。

```bash
hostname
ls -ld /opt/keybridge /etc/keybridge
find "$HOME" -maxdepth 3 -type f -path '*/scripts/install.sh' -print
```

`hostname` が想定した `hidpi` かを確認します。`/opt/keybridge` もなければ、アプリ配置より前にインストーラーが停止している可能性があります。
`find` で見つかった展開フォルダーへ移動し、インストーラーを再実行して停止箇所を確認してください。例えば `/home/pi/keybridge-upload.abcdef/scripts/install.sh` が見つかった場合:

```bash
cd /home/pi/keybridge-upload.abcdef
sudo bash scripts/install.sh
```

`abcdef` は、実際に見つかったフォルダー名に置き換えます。**最後に `Installation complete.` が表示されることを確認してから `sudo reboot` を実行します。**
エラーで止まった場合は、その出力を確認・共有してください。再起動だけでは未登録のサービスは作成されません。

旧版で `Existing USB controller overlay` が出る場合、`[cm5]` など他機種向けの設定まで競合と誤判定している可能性があります。設定行とその機種条件は次で確認できます。

```bash
grep -nE '^\[|^[[:space:]]*dtoverlay[[:space:]]*=[[:space:]]*(dwc2|dwc-otg)' /boot/firmware/config.txt
```

最新版は機種条件を考慮します。旧版を展開済みの場合は、開発PCから修正版をSCPし、その展開フォルダーのインストーラーを再実行してください。
`[cm5]` 内の設定をZero 2 W用に削除・書き換える必要はありません。`[all]` / `[pi02]` などZero 2 Wにも適用される箇所に既存のUSB設定がある場合は、引き続き競合を確認します。

Webが停止中の場合の起動:

```bash
sudo systemctl start keybridge-web
```

ログに `ModuleNotFoundError`、環境ファイルの読み込み失敗、JSONの検証エラー、`Permission denied` などがあれば、その原因を先に修正します。
`Start request repeated too quickly` が出る場合は、原因修正後に `sudo systemctl reset-failed keybridge-web`、`sudo systemctl start keybridge-web` を実行します。
認証設定ファイルの中身を表示・共有する必要はありません。

### 3. 8000番ポートで待ち受けているか確認する

**Pi上で実行:**

```bash
sudo ss -ltnp 'sport = :8000'
```

配布したsystemd設定では、`LISTEN` の行に **`0.0.0.0:8000`** とGunicornのプロセスが表示される想定です。

- 見出しだけで行がない: 8000番で待ち受けていません。Webサービスの状態・ログへ戻ります。
- `127.0.0.1:8000` のみ: Pi自身からだけ接続できる設定です。手動起動や独自のサービス設定がないか確認します。
- 別のプロセスが8000番を使用: Webサービスのログにポート競合が出ていないか確認します。

実際に読み込まれているサービス設定は `systemctl cat keybridge-web` で確認できます。通常のLAN運用では `ExecStart` に `--bind 0.0.0.0:8000` が入ります。
HTTPSプロキシを別途設定している場合は、その構成に合わせて確認してください。

### 4. Pi自身からHTTP応答を確認する

**Pi上で実行:**

```bash
curl --noproxy '*' -i --connect-timeout 3 --max-time 10 http://127.0.0.1:8000/api/status
```

`curl: command not found` の場合は、Pi上で `sudo apt-get install -y curl` を実行してから再試行します。

このコマンドは認証情報を送らないため、**`HTTP/1.1 401 UNAUTHORIZED` と `WWW-Authenticate: Basic ...` が返れば、期待する応答です。** この段階ではパスワード入力は不要です。

| 結果 | 意味・次の確認 |
| --- | --- |
| HTTP 401とBasic認証のヘッダー | Webサーバーへ到達できている。次のLANからの確認へ進む |
| `curl: (7)` / `Connection refused` | 接続できていない。サービス停止・待ち受け先・起動ログを確認 |
| `curl: (28)` / タイムアウト | 応答がない。サービスのログとPiの負荷・通信設定を確認 |
| HTTP 500 | HTTPサーバーには到達。Webサービスのjournalで例外を確認 |

続いて、同じPi上で **PiのLAN側IP** にも接続してみます。

```bash
curl --noproxy '*' -i --connect-timeout 3 --max-time 10 http://192.168.1.50:8000/api/status
```

こちらも401なら、Pi自身からLAN側の待ち受けへ接続できています。
`127.0.0.1` は成功するのにLAN側IPでは失敗する場合は、IPが正しいか、待ち受け先が `0.0.0.0:8000` か、Pi側のファイアウォールで制限していないかを確認します。

### 5. 操作用PCから接続する

**WindowsのPowerShellで実行（IPは置き換える）:**

```powershell
Test-NetConnection -ComputerName 192.168.1.50 -Port 8000
curl.exe --noproxy "*" -i --connect-timeout 3 --max-time 10 http://192.168.1.50:8000/api/status
```

- `TcpTestSucceeded : True`、curlもHTTP 401: PCから到達できています。ブラウザで **`http://192.168.1.50:8000`** を開き、Web用の認証情報を入力します。
- `TcpTestSucceeded : False`: PiのIP、同じLANか、ゲストWi-Fi・APの端末分離、VPN・ファイアウォールで8000/tcpが遮断されていないかを確認します。Pi上では成功しているかも比較してください。
- IP指定では開くが `hidpi.local` では開かない: ホスト名の解決を確認します。当面はIP指定で利用できます。

ブラウザのURLは **`http://` と `:8000` を含めて** 入力します。標準のインストールではHTTPSを設定していません。
スマートフォンの場合も同じIPのURLで確認します。ルーターによっては、同じSSIDでもゲスト接続や端末分離により通信できない場合があります。

### 6. 原因が分からない場合に共有する結果

次の結果があると、どこで止まっているかを確認できます。**最初の4コマンドはPi上、最後は操作用PCで実行します。**

```bash
hostname -I
sudo systemctl status keybridge-web keybridge-gadget --no-pager -l
sudo ss -ltnp 'sport = :8000'
curl --noproxy '*' -i --connect-timeout 3 --max-time 10 http://127.0.0.1:8000/api/status
```

```powershell
Test-NetConnection -ComputerName 192.168.1.50 -Port 8000
```

Webが起動失敗している場合は、手順2のjournalも確認・共有してください。Web用パスワード、パスワードハッシュ、署名鍵は共有しないでください。

## 補足：インストーラーによる変更

1. `dpkg-query` で `python3`, `python3-venv`, `python3-pip`, `kmod` の導入状態を確認。すべて導入済みなら `apt-get update` と `apt-get install` を両方スキップ。不足・未設定のパッケージがある場合だけAPTの一覧を更新し、そのパッケージをインストール。
2. 専用の `keybridge` システムユーザー・グループを作成。
3. アプリを `/opt/keybridge` に配置。コードはroot所有、Webサービスから書き換え不可。
4. `python3 -m venv /opt/keybridge/.venv` と `pip install -r requirements.txt` を実行。
5. `/etc/keybridge/keybridge.env` をroot所有・0600で作成。パスワードハッシュとランダムなCSRF署名鍵を保存。
6. boot設定を `config.txt.keybridge.bak` にバックアップして、次の管理ブロックを追記。

   ```ini
   # BEGIN KeyBridge
   [all]
   dtoverlay=dwc2,dr_mode=peripheral
   # END KeyBridge
   ```

7. `/etc/modules-load.d/keybridge.conf` に `dwc2` と `libcomposite` を設定。
8. `/etc/udev/rules.d/99-keybridge-hid.rules` に `/dev/hidg0` の `root:keybridge`・0660ルールを登録。
9. 2つのsystemdサービスを登録・有効化。更新時はWebサービスを停止し、再起動後に新しい構成で起動。

`cmdline.txt`、Wi-Fi、SSHの既存設定は変更しません。既存のマクロと認証情報は保持します。
boot設定は通常 `/boot/firmware/config.txt`、なければ `/boot/config.txt` を使います。変更せずに確認するには:

```bash
python3 scripts/configure-boot.py /boot/firmware/config.txt --dry-run
```

Zero 2 Wに適用される可能性のある既存の `dtoverlay=dwc2...` / `dwc-otg...` があれば、自動変更せず行番号付きで停止します。重複・競合を確認して再実行してください。
`[cm5]` など別機種向けの条件内にある設定は保持し、インストールを続行します。機種条件は[Raspberry Pi公式の条件付きフィルター](https://www.raspberrypi.com/documentation/computers/config_txt.html#conditional-filters)に基づきます。
`include` 先の設定や既存の `g_ether` / `g_hid` など、別のUSB Gadget構成は自動解析・解除しません。使用中なら先に整理してください。
overlayの指定は[Raspberry Piの定義](https://github.com/raspberrypi/firmware/blob/master/boot/overlays/README)に基づきます。[boot設定の反映には再起動が必要](https://www.raspberrypi.com/documentation/computers/config_txt.html)です。

## Web操作

再起動後、同じLANの別端末から `http://hidpi.local:8000` または `http://PiのIP:8000` を開き、Web用の認証情報を入力します。
`data/macros.json` がなければ、Hello World・メール・フォーム入力のサンプルを生成します。

- ボタンはJSON定義順。画面上部にUSB接続状態を表示します。
- デバイスなし・操作権限なし・USB未接続では送信ボタンを無効にします。
- 送信中は重複操作を防止。複数端末から同時実行すると、後続をHTTP 409で拒否します。完了後に再操作してください。キューや自動再送はありません。
- 「JSONをインポート」で現在の設定を完全置換し、ボタンを更新します。
- 「エクスポート」で保存済みJSONを `macros.json` としてダウンロードします。アップロード時の空白・改行も保持します。
- CSRFトークンは1時間有効。期限エラーが出たら画面を再読み込みしてください。

送信前にWindows側の入力フォーカスを確認してください。途中で切断すると既に一部が入力されている可能性があります。入力先を確認してから再操作します。
「USB接続済み」はUDCの `configured` 状態を示し、文字の正確な入力やアプリのフォーカスまでは確認できません。

## JSON形式

保存先は `/opt/keybridge/data/macros.json`。バージョン1の例:

```json
{
  "version": 1,
  "macros": [
    {
      "id": "hello",
      "label": "挨拶を入力",
      "steps": [
        {"type": "text", "value": "Hello World!"},
        {"type": "key", "value": "TAB"},
        {"type": "combo", "keys": ["CTRL", "A"]},
        {"type": "delay", "ms": 300},
        {"type": "key", "value": "ENTER"}
      ]
    }
  ]
}
```

| 操作 | フィールド | 動作 |
| --- | --- | --- |
| `text` | `value`: 文字列 | US ASCIIを順次入力。改行・タブにも対応。CRLFはEnter 1回 |
| `key` | `value`: キー名 | 単独キーを押下・解放 |
| `combo` | `keys`: 配列 | 複数キーを同時押下・解放 |
| `delay` | `ms`: 整数 | 0–60000ミリ秒待機 |

表示名には日本語を使えます。**送信文字列**はASCII表示文字と改行・タブのみ対応し、かな・漢字などはインポート時と実行前にエラーになります。
`text` の大文字・記号には必要なShiftを付加します。`key` / `combo` の英字は物理キー名です。`["CTRL", "A"]` はCtrl+A、`["SHIFT", "A"]` はShift+Aです。

キー名は大文字・小文字を区別しません:

- `A`–`Z`, `0`–`9`, US記号、`SPACE`
- `ENTER`, `TAB`, `ESC` / `ESCAPE`, `BACKSPACE`, `DELETE`
- `UP`, `DOWN`, `LEFT`, `RIGHT`, `HOME`, `END`, `INSERT`, `PAGEUP`, `PAGEDOWN`
- `F1`–`F12`, `CAPSLOCK`, `PRINTSCREEN`, `SCROLLLOCK`, `PAUSE`
- `CTRL` / `LCTRL`, `SHIFT` / `LSHIFT`, `ALT` / `LALT`, `WIN` / `WINDOWS` / `GUI` / `LWIN`
- `RCTRL`, `RSHIFT`, `RALT`, `RWIN`

1レポートは通常キー最大6個と修飾キー8個まで。同じ物理キー・修飾キーの重複は拒否します。
配列変換は `USLayout` に分離してあり、将来のJIS対応時に差し替えられます。

検証上の制限:

- UTF-8 JSON（BOMも可）、最大256 KiB、最大100マクロ。`macros: []` も有効。
- `id`: 重複不可、英数字・`_`・`-` の1–64文字。`label`: 空白だけではない1–100文字。
- 1マクロ1–500ステップ、1text最大10000文字、合計最大10000キー操作。
- 押下時間・入力間隔・delayを合わせた予定実行時間は60秒以内。USB I/O待ち時間は別枠。
- 不明フィールド、重複JSONフィールド、未知の操作、無効なキー、未対応文字は拒否。

検証後、同じディレクトリの0600一時ファイルへ書き、`fsync` と `os.replace` で置換します。
不正JSONや置換前の書き込み失敗では既存設定を保持します。起動時に既存JSONが破損していた場合は、勝手にサンプルへ上書きせず起動エラーにします。
SSHでJSONを直接編集した場合はWebサービスを再起動してください。Webインポートは即時反映されます。

## API

全ページ・静的ファイル・APIに認証が必要です。最初のアクセスで従来どおりHTTP Basic認証を行い、以後1時間は署名付きCookieで認証します。Piの負荷を抑えるため、有効なCookieがあればパスワードのハッシュ検証を繰り返しません。ボタン操作・接続状態確認も軽い署名確認で処理します。追加のデータベースや依存パッケージは不要です。

Cookieは `HttpOnly`・`SameSite=Strict` で、期限は操作のたびに延長しません。期限切れ時は、ブラウザが保持するBasic認証情報で再検証します。Cookieを保持しないAPIクライアントも従来どおりBasic認証を使えますが、毎回パスワードを検証します。POSTには引き続き、ページのmeta要素から取得した `X-CSRF-Token` が必要です。

| Method | Path | 内容 |
| --- | --- | --- |
| GET | `/` | 操作画面、CSRFトークン |
| GET | `/api/macros` | `version` と `macros: [{id, label}]`（定義順） |
| POST | `/api/macros/<id>/execute` | 登録マクロを同期実行。完了時 `{ok: true, id}` |
| POST | `/api/config/import` | multipart/form-data、`file` フィールドにJSON 1個 |
| GET | `/api/config/export` | `macros.json` ダウンロード |
| GET | `/api/status` | `hid` のノード・権限・UDC状態、`busy`, `layout` |

エラー形式は `{"error": {"code": "...", "message": "..."}}`。
主なHTTPステータスは入力400、認証401、CSRF403、不明ID404、実行中409、サイズ413、保存障害500、HID利用不可503です。
任意の操作列を受け取るAPIはありません。実行APIのリクエスト本文で登録済み内容を変更することはできません。

## サービスと設定

```bash
sudo systemctl status keybridge-gadget keybridge-web --no-pager
sudo journalctl -u keybridge-gadget -u keybridge-web -b --no-pager
sudo journalctl -u keybridge-web -f
```

- `keybridge-gadget`: rootのoneshotでConfigFSへ8バイトのBoot Keyboardを作成しUDCへbind。失敗時は再試行。
- `keybridge-web`: 専用ユーザーでGunicornを起動。Gadget初期化後に起動しますが、Gadget失敗時もWebで状態確認可能。プロセス異常終了時は再起動。
- Webにroot権限は付与せず、HIDのグループ権限と設定ディレクトリの書き込み権限を使います。
- Gunicornは **1 worker / 4 threads**。排他制御はプロセス内ロックのため、worker数を増やしたり複数のWebプロセスを起動したりしないでください。
- USB切断時は上限付き非ブロッキングI/Oで503を返し、可能な限り全キー解放を試みます。各マクロでデバイスを開き直すため、古いFDを保持しません。
- 他のGadgetは取り外しません。KeyBridgeのHIDがhidg0として作れない場合は停止します。

`/etc/keybridge/keybridge.env` の変更は `sudo systemctl restart keybridge-web` で反映します。

| 変数 | 初期値・用途 |
| --- | --- |
| `KEYBRIDGE_USERNAME` | 対話入力したWebユーザー名 |
| `KEYBRIDGE_PASSWORD_HASH` | PBKDF2-SHA256ハッシュ。平文パスワードは保存しない |
| `KEYBRIDGE_SECRET_KEY` | 生成した64桁ランダム16進文字列。認証Cookie・CSRF署名用 |
| `KEYBRIDGE_KEY_INTERVAL_MS` | `20`、キー解放後の待ち時間 |
| `KEYBRIDGE_KEY_HOLD_MS` | `20`、キー押下の維持時間 |
| `KEYBRIDGE_CONFIG` | 省略時 `/opt/keybridge/data/macros.json` |
| `KEYBRIDGE_HID_DEVICE` | 省略時 `/dev/hidg0` |

初期値は押下20 ms + 解放後20 msで約25文字/秒。時間設定は0–1000 msです。
時間変更で既存マクロが60秒上限を超えた場合は起動時にエラーになります。認証設定がない、署名鍵が短い場合も起動しません。

認証の再設定:

```bash
sudo /opt/keybridge/.venv/bin/python /opt/keybridge/scripts/configure-auth.py --output /etc/keybridge/keybridge.env
sudo systemctl restart keybridge-web
```

署名鍵とタイミング設定も新しくします。画面を再読み込みしてください。ブラウザが古いBasic認証を保持する場合は、そのサイトの認証情報を消すか新しいプライベートウィンドウで開きます。
ユーザー名・パスワードハッシュ・署名鍵のいずれかを変更してWebサービスを再起動すると、発行済みの認証Cookieも無効になります。

HTTPの平文通信は**信頼できるLAN内の試作・開発用**です。インターネットへ直接公開しないでください。
通信保護が必要ならHTTPSリバースプロキシを前段に置き、Gunicornのbindを `127.0.0.1:8000` に変更します（プロキシと証明書の自動設定は含みません）。
エクスポートしたJSONにも入力文字列が含まれるため、取り扱いを確認してください。

## SCPで更新・実機デバッグ

PCで修正して梱包・転送します。更新前にWebからJSONをエクスポートしておくと戻しやすくなります。

```bash
# 開発PC
bash scripts/package.sh
scp dist/keybridge.tar.gz pi@hidpi.local:~/keybridge.tar.gz
ssh pi@hidpi.local
```

```bash
# Pi: 空の展開先へ展開
upload_dir=$(mktemp -d "$HOME/keybridge-upload.XXXXXX")
tar -xzf ~/keybridge.tar.gz -C "$upload_dir"
cd "$upload_dir"
sudo bash scripts/install.sh
sudo reboot
```

再インストール時も `/opt/keybridge/data/macros.json` と認証ファイルを上書きしません。
必要なシステムパッケージが導入済みなら、APTの一覧取得・インストールは行いません。Python仮想環境の作成・確認と `pip install -r requirements.txt` は引き続き実行します。
認証Cookieに対応した版への更新でも、既存のユーザー名・パスワードをそのまま使えます。認証の再設定は不要です。
本番設定は展開フォルダーから独立しています。展開先の `data/macros.json` を編集しても本番設定は変わりません。
導入途中で失敗した場合、Webが停止したままになることがあります。原因を修正して再実行してください。

Python / HTML / CSS / JSだけの小修正は、対象ファイルをSCPしてサービス停止中に配置することもできます。

```bash
# 開発PC
scp app/hid_keyboard.py pi@hidpi.local:~/hid_keyboard.py
```

```bash
# Pi
sudo systemctl stop keybridge-web
sudo install -o root -g root -m 0644 ~/hid_keyboard.py /opt/keybridge/app/hid_keyboard.py
sudo systemctl start keybridge-web
sudo journalctl -u keybridge-web -n 80 --no-pager
```

スクリプト・systemd変更は再インストール・再起動を推奨します。ログをPCへ持ち帰る場合:

```bash
# Pi
sudo journalctl -u keybridge-gadget -u keybridge-web -b --no-pager > ~/keybridge-debug.log
```

```bash
# 開発PC
scp pi@hidpi.local:~/keybridge-debug.log .
```

ログにマクロ本文・平文パスワードは出しません。アクセス元IPやマクロIDは含まれる場合があります。

## ローカル開発・テスト（開発PC向け）

以下は開発PCでの検証手順です。インストール済みのPiはsystemdで自動起動するため、通常利用ではこの節の手動起動は不要です。
Raspberry Piがなくても、HIDをモック化したテストを実行できます。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/pytest -q --cov=app --cov-report=term-missing
.venv/bin/ruff check .
bash -n scripts/*.sh
```

WindowsではVS Code開発コンテナーかWSLを使用してください。ネイティブPythonでは `.venv/bin/python` を `.venv\Scripts\python.exe` に読み替えられますが、Linux固有のI/OテストとGadgetスクリプトはLinuxが必要です。

Web画面だけ起動する場合:

```bash
.venv/bin/python scripts/configure-auth.py --output .env
set -a
. ./.env
set +a
.venv/bin/python -m app.main
```

`http://127.0.0.1:8000` を開きます。HIDがなければ送信ボタンは無効、APIは503です。
認証情報の `.env` と自動生成される `data/macros.json` はGit追跡・配布の対象外です。

テスト対象はASCIIと各キーのレポート、例外時のキー解放、切断・再接続・タイムアウト、事前検証、待機、排他、JSON検証・永続化・保存失敗、認証・CSRF・API・アップロード制限、boot設定のバックアップ・冪等性です。認証では、Cookie発行後にパスワード検証を繰り返さないこと、期限切れ・改ざん・設定変更時の無効化も確認します。

## 実機チェック（未実施）

1. 再起動後、Gadget・Webサービスの起動と、`ls -l /dev/hidg0` の `root keybridge`・0660を確認。
2. USBデータ端子をWindowsへ接続し、標準USBキーボードとして認識されるか確認。
3. 次の単独キーマクロをインポートし、メモ帳へフォーカスして実行。

   ```json
   {"version":1,"macros":[{"id":"single","label":"単独 a","steps":[{"type":"key","value":"A"}]}]}
   ```

4. サンプルJSONへ戻し、Hello World、Enter、Tab、Ctrl+A、Shift付き記号を確認。US配列・IMEオフ・Caps Lockオフにする。
5. 不正JSON・日本語送信文字のJSONが拒否され、既存ボタンが維持されるか確認。
6. エクスポート内容がインポート内容と一致し、Pi再起動後も設定が残るか確認。
7. USBケーブルを外してもWebが停止せず、再接続後に入力できるか確認。送信途中の切断はメモ帳で試す。
8. 2台から同時送信し、入力が混ざらず後続へ409が返るか確認。
9. 再起動後、手動操作なしにGadget・Webが起動して入力できるか確認。

## トラブルシューティング

| 症状 | 確認箇所 |
| --- | --- |
| UDCが空 / Gadget失敗 | モデル、dwc2 peripheral設定、再起動。`journalctl -u keybridge-gadget -b` |
| Windowsに認識されない | PWR INではなくUSB端子か、データ対応ケーブルか、別GadgetがUDCを占有していないか |
| hidg0 belongs to another gadget / UDC busy | 既存のg_ether・g_hid・別のConfigFS Gadget。自動解除しません |
| 503 / HID権限なし | USB接続、`ls -l /dev/hidg0`、Gadgetログ |
| 記号・文字が違う | WindowsのUS/JIS配列、IME、Caps Lock、フォーカス。遅いアプリでは入力間隔を増やす |
| ボタンを押してから入力開始まで遅い | 最新版へ更新し、ブラウザでCookieを許可して画面を再読み込み。初回認証と1時間ごとの更新時にはパスワード検証が必要。毎回遅い場合は通信・Piの負荷・マクロ先頭のdelay・USB接続を確認。キー間隔の設定は入力開始後の速度に影響 |
| Webにアクセスできない | [Webにアクセスできないときの確認](#webにアクセスできないときの確認)を順番に実行 |
| 401 | SSH用ではなくWeb用の認証情報か。必要ならconfigure-auth.pyで再設定 |
| 403 / CSRF期限切れ | 画面を再読み込み。別サイトからのPOSTは拒否 |
| インポート400 / 413 | UTF-8、.json、必須フィールド、キー名、256 KiB・60秒制限 |
| Web起動失敗 | 環境ファイル、JSON破損・権限、ディスク空き、時間設定変更後の60秒制限 |

Gadgetを再作成する場合は、送信中でないことを確認して実行します。

```bash
sudo systemctl stop keybridge-web
sudo systemctl restart keybridge-gadget
sudo systemctl start keybridge-web
```

停止・自動起動解除:

```bash
sudo systemctl disable --now keybridge-web
sudo systemctl disable --now keybridge-gadget
```

OSのUSB設定も戻すには、config.txtのKeyBridge管理ブロックと `/etc/modules-load.d/keybridge.conf`、`/etc/udev/rules.d/99-keybridge-hid.rules` を取り除いて再起動します。
バックアップ全体を復元すると後から追加したOS設定が失われる場合があるので、内容を確認してください。

## ファイル構成

```text
app/
  main.py                 Flask・認証・CSRF・API
  hid_keyboard.py         USキー変換・8バイトレポート・HID I/O
  macro_executor.py       検証・順次実行・排他
  config_manager.py       JSON・永続化・アトミック置換
  templates/index.html    操作画面
  static/                 CSS・JavaScript
data/macros.example.json  配布用サンプル
data/macros.json          実行時設定（自動生成・Git対象外）
scripts/
  setup-gadget.sh         ConfigFS初期化・停止
  install.sh              Piへの導入・更新
  install-packages.sh     必須パッケージ確認・不足時のみAPT実行
  configure-boot.py       boot設定の追記
  configure-auth.py       認証ファイル生成
  package.sh              SCPアーカイブ作成
systemd/                  自動起動サービス
tests/                    実機不要の自動テスト
```

USB実装の参照: Linux公式の[HID Gadget](https://docs.kernel.org/usb/gadget_hid.html)、[ConfigFS Gadget](https://docs.kernel.org/usb/gadget_configfs.html)。VID/PIDは試作用の例示値です。製品として配布する場合は割り当て済みIDへ変更してください。
認証・アップロード制限・CSRFの参照: [Flaskセキュリティガイド](https://flask.palletsprojects.com/en/stable/web-security/)。
