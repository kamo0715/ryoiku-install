# 療育カリキュラム管理 v2.20 — Docker LANテスト版

小学校高学年〜高校生向けの**最新版v2.20**を、Ubuntu Server（Linux / x86_64・Docker Compose v2）で動かすためのテスト環境です。既存のロリポップ用ソースには手を加えません。

> **テスト専用**：HTTP通信です。パスワードや支援内容を同じネットワーク上で傍受される可能性があります。**実在の児童・生徒の個人情報、実際の個別支援計画、運用用のAPIキーは入力しないでください。**本番利用はTLS/HTTPS、事業所の情報管理ルール、ネットワーク分離を含む別設計が必要です。

## 1. 使用条件

- Ubuntu Serverなどの**Linux Docker Engine** / Docker Compose v2
- AMD64 / x86_64 CPU（同梱Python 3.13ライブラリがLinux x86_64用のためARM64不可）
- Ubuntu Serverが持つ**RFC1918プライベートIPv4**アドレス（例 `192.168.1.50`）
- LAN内の接続元範囲（例 `192.168.1.0/24`）
- 任意ポート（標準 `18080`）、ほかのサービスと競合しないこと

Dockerは **Linux hostネットワーク**を使いますが、アプリは指定したLAN IPv4にしかバインドしません。加えて指定CIDR以外の接続元をHTTP 403で拒否します。`X-Forwarded-For` も信用しません。ルーター側ではポート転送・公開を設定しないでください。localhost (`127.0.0.1`) からは接続できません。LAN IPでアクセスします。

## 2. 旧Docker版の自動停止・削除（v2.20 更新版）

新しい `install-lan-test.sh` は先に **v2.20のDockerイメージをビルド**し、成功後に旧コンテナを識別して削除し、新コンテナを起動します。

識別対象は `minecraft-ryoiku-web`、`ryoiku-lan-test`、`ryoiku-curriculum`、`ryoiku-web` です。ただし、名前だけでなくDockerイメージ名かComposeラベルから**療育アプリ本体であることを確認できたものだけ**を削除します。識別に失敗した場合は中止します。関連性を確認できないコンテナ、録画サーバー、Minecraft、Tailscaleは操作しません。

事前確認のみ：

```bash
./remove-old-ryoiku.sh --check
```

実際の削除：`install-lan-test.sh` の中で自動実行されます。削除するのは**コンテナ本体のみ**です。既存のDockerボリューム、SQLite DB、旧イメージ、Compose設定、バックアップは消去しません。ただし新コンテナは別ボリューム `ryoiku_lan_test_data` を使用するため、旧データは**自動移行されません**。実際の記録はこのHTTPテスト環境に移さないでください。

既存のコンテナ名が異なる場合は無理に削除せず、`docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'` で確認してください。

## 3. ZIPで配布された場合：インストール

```bash
unzip ryoiku-v2.20-docker-lan-test.zip
cd ryoiku-v2.20-docker-lan-test
chmod +x install-lan-test.sh
./install-lan-test.sh
```

`install-lan-test.sh` は既存 `.env` を**上書きしません**。既定ルートのLANアドレスとサブネットを自動判定し、`.env` を生成します。検出結果が誤りの場合は、起動前に `.env` を修正してください。

手動設定：

```bash
cp .env.example .env
nano .env
# LAN_BIND_IP=192.168.1.50
# LAN_ALLOWED_CIDR=192.168.1.0/24
# RYOIKU_PORT=18080
chmod 600 .env
docker compose up -d --build
```

`LAN_BIND_IP=0.0.0.0`、公開IP、広すぎるサブネットなどは**起動を拒否**します。

## 4. GitHubのソースから構築する場合

```bash
git clone https://github.com/kamo0715/ryoiku-install.git
cd ryoiku-install/docker-lan-test
./prepare.sh
./install-lan-test.sh
```

`prepare.sh` は親リポジトリで保存されている**公式v2.20の配布ZIP**をSHA-256照合してから展開します。Dockerイメージに含めるのはそのv2.20アプリとライブラリです。

## 5. 初期登録と画面を開く

Ubuntu Serverで、初回登録コードを確認します。

```bash
docker compose ps
docker compose exec -T ryoiku cat /data/INITIAL_ADMIN_CODE.txt
```

例：Ubuntu ServerのLAN IPが `192.168.1.50` の場合は、**同じLANのPCやスマホ**で次を開きます。

```text
http://192.168.1.50:18080/first-setup
```

初回登録コード、管理者ユーザー名、**16文字以上**のパスワードを入力します。登録後、初回コードは破棄されます。以後は `/login` からログインします。実在の児童情報ではなく架空のデモデータで検証してください。

## 6. 確認する機能

- 職員ログイン・職員登録・権限
- 架空の利用者登録、個別支援計画
- Minecraftとそれ以外の活動、同日複数カリキュラム
- 職員用、関係機関用、**小学高学年〜高校生向け利用者用**スケジュール
- PDF / Word / Excel出力、A4横1ページ配置
- AI送信前の匿名化プレビュー（外部AI APIへの送信は行わない）
- 操作ログ、復旧、データ保存

```bash
# 状態を確認
docker compose ps
# エラーログ（機密情報を含む可能性があるため共有時に注意）
docker compose logs --tail=100 ryoiku
# 動作確認（IPは自分のサーバーに置換）
curl --noproxy '*' -i http://192.168.1.50:18080/healthz
```

## 7. 停止・再起動・更新

```bash
docker compose stop      # 停止（データ維持）
docker compose start     # 再開
docker compose down      # コンテナ削除（名前付きボリュームは維持）
docker compose up -d --build    # 再構築して起動（データ維持）
```

アプリの秘密鍵とSQLite DBは専用のDockerボリューム `ryoiku_lan_test_data` に保存されます。更新前は**DBとsecrets.envを必ず一緒にバックアップ**してください。絶対に運用データを使わないでください。

**注意：** `docker compose down -v` はデータを完全削除します（テスト環境を初期化する場合にだけ使ってください）。既存の録画サーバー・Minecraft・TailscaleなどのDockerコンテナは操作しません。

## 8. LANアクセスの追加保護（任意）

ホストOSにUFWがあり、**すでに安全に有効化されている場合のみ**、LANだけ許可できます。UFWを初めて有効化するとSSH接続を失う場合があるため、自動では有効化しません。

```bash
sudo ufw insert 1 allow from 192.168.1.0/24 to 192.168.1.50 port 18080 proto tcp
sudo ufw insert 2 deny from any to 192.168.1.50 port 18080 proto tcp
```

LANのアドレスとポートは `.env` と合わせて書き換えてください。Docker `host` ネットワークを使うので、Docker公開ポートのNATによるUFW迂回を避けています。ただし、hostネットワークはネットワーク名前空間の分離を持たないため、テスト用途に限定します。

## 9. 安全設計上の制限

- LANアクセスを制限するだけで、**HTTPSや完全なネットワーク隔離は提供しません**
- `127.0.0.1` やTailscale IP、パブリックIPでの待ち受けを行いません
- 外部AIの利用を設定した場合は、送信前匿名化の職員確認を必須としてください
- 初回登録パスワードや秘密鍵はGitHub、チャット、スクリーンショットに記載しないでください
- NAS等へボリュームを移す場合、暗号化鍵とDBの両方を保護してください
- ロリポップ本番環境・その他のDockerサービスには手を加えません

## 検証状況

FastAPIの起動・初期管理者登録・ログイン・静的ファイル・LANアクセス拒否・Hostヘッダー拒否のローカル動作試験を通過しています。Docker Engineの実コンテナ試験は別途GitHub Actionsで実施します。

## PDF転記後の保存不具合の修正（2026-11-19）

PDF・文章の解析結果を表示する画面で、保存フォームの送信先が省略され、解析エンドポイントに再投稿される不具合を修正しました。`docker/overrides/support_form.html` がDockerビルド時に反映されます。保存先は `/children/<ID>/support/new` です。本人・保護者・アセスメントの3チェックと原本確認は引き続き必須です。既存のDockerボリューム（`ryoiku_lan_test_data`）を保持したまま、`docker compose up -d --build` で反映できます。

新しい配布ZIP `ryoiku-v2.20-docker-lan-pdf-savefix.zip` は、2026-11-19付の修正版です。古い同名ZIPを無条件に上書きしないでください。

### すでに起動している環境の更新

`cd`で以前の`ryoiku-v2.20-docker-lan-test`のフォルダへ移動し、更新版の`fix-pdf-save-local.sh`を置いて`sudo ./fix-pdf-save-local.sh`を実行すると、画面テンプレートのみ安全に差し替え、データボリュームを保持したまま対象コンテナを再ビルドします。最新版ZIPを展開し直す場合は旧データのバックアップを先に実施してください。