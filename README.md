# 療育カリキュラム管理（ロリポップ向け）

小学校高学年〜高校生の放課後等デイサービス等における、個別支援計画・支援活動・日別スケジュール・帳票を扱うWebアプリです。

**最新ソース: v2.24** （v2.18の匿名化強化、v2.19の児童・生徒用日別帳票、v2.20の高学年〜高校生向けレイアウトを含む）

## トークン不要のwget導入（最新 v2.23）

公開GitHub Releaseから、複数の**新規**カリキュラムをまとめて生成できるv2.23を、SHA-256照合付きで導入できます。

```bash
cd ~
wget -qO install-ryoiku-v2.23-wget.sh https://raw.githubusercontent.com/kamo0715/ryoiku-install/main/install-ryoiku-v2.23-wget.sh
bash install-ryoiku-v2.23-wget.sh
```

`--download-only` は取得・検証だけを行います。既存のv2.22／v2.21／v2.20のLAN設定を利用でき、Dockerボリューム `ryoiku_lan_test_data` はそのまま保持します。新しいDockerイメージをビルドしてから検証済み旧療育コンテナのみ入れ替えます。HTTPのテスト用につき実在する児童の個人情報を入力しないでください。

## バージョン別ダウンロード（GitHub Releases）

[Releases一覧](https://github.com/kamo0715/ryoiku-install/releases) に、旧Linux用の自己完結型 `.sh`（v2.2〜v2.8）、v2.9差分、ロリポップ向け完全版（v2.11〜v2.20）を掲載しています。
v2.11〜v2.19は保存したアプリファイルと共通依存ライブラリから再構成したZIP、v2.20は元ZIPのSHA-256を照合して復元したものです。
今後は版別ソースを `release-sources/` に追加して `main` にプッシュすると、自動リリースワークフローが未公開の版を作成します。詳しくは [リリース管理手順](docs/RELEASES.md) を参照してください。

## 公開GitHubからwgetでv2.21を導入（トークン不要）

リポジトリとv2.21の配布ファイルは公開されています。Ubuntu Server（AMD64）にwgetで直接ダウンロードでき、GitHubのPersonal Access Tokenは不要です。ZIPは公開済みReleaseのSHA-256で検証し、エラー時は旧Dockerコンテナを変更しません。

```bash
sudo apt update && sudo apt install -y wget unzip
wget -O setup-ryoiku-docker-v2.21-wget.sh https://raw.githubusercontent.com/kamo0715/ryoiku-install/main/setup-ryoiku-docker-v2.21-wget.sh
bash -n setup-ryoiku-docker-v2.21-wget.sh
bash setup-ryoiku-docker-v2.21-wget.sh
```

ダウンロードと検証だけ実行する場合：`bash setup-ryoiku-docker-v2.21-wget.sh --download-only`。詳しくは[Docker LAN版の手順](docker-lan-v2.21/README_DOCKER_LAN.md)を参照してください。LANテスト環境はHTTPのため**実在の利用者情報を入力しないでください**。

## v2.24：個別支援計画だけに下書きを限定・モバイル操作を簡単に

- **下書き保存は個別支援計画のみ。** 担当者・利用者単位に暗号化保存し、正式な計画履歴に混入しません。
- カリキュラム生成は完成した活動を「保存済み・職員確認前」として表示。過去の活動 `draft` 状態は既存履歴を維持して移行します。
- カリキュラム作成画面は「複数まとめて作る」「1件だけ作る」「保存済みを使う」の3択。不要な入力欄を隠します。
- 日別編集画面では活動の選択・順番・出力先を優先し、詳細編集は必要に応じて展開します。
- 360px／390pxスマホ、820pxタブレット、1280pxデスクトップで表示・操作を検証しました。
- [v2.24 リリース](https://github.com/kamo0715/ryoiku-install/releases/tag/v2.24) / Docker LAN版 `docker-lan-v2.24/`

## v2.23：新規カリキュラムを2〜8件まとめてAI生成

カリキュラム作成画面の「新しいカリキュラムを複数まとめて生成」で、それぞれ異なる活動の種類・時間・テーマ・配慮事項を指定できます。従来の「保存済みカリキュラムを追加」とは別機能であり、複数の**新規**カリキュラムを1回の操作で生成し、1日の流れにまとめます。

- 新規2〜8件を同一利用者へ一括生成して自動的に日別予定へ選択
- 外部AIへの情報最小化・全件の送信前確認、最大2件の並列生成
- 全件生成成功後にのみSQLiteトランザクションで一括保存
- [GitHub Release v2.23](https://github.com/kamo0715/ryoiku-install/releases/tag/v2.23)
- Docker LAN版：`docker-lan-v2.23/`、ロリポップ版：`release-sources/v2.23/`

## v2.22：一日で複数のカリキュラムを選択して流れを作成

カリキュラム生成画面から、保存済みの活動を最大8件チェックして日別支援の流れへ進めます。さらに新規活動を生成する場合も、既存の最大7件を選んで一日の流れへ直接組み込めます。時刻・実施順・休憩を調整し、職員用／関係機関用／利用者用のPDF・Word・Excelを出力します。外部AI送信前確認、異なる利用者の選択拒否、既存DB保護を維持しています。

- [v2.22 GitHub Release](https://github.com/kamo0715/ryoiku-install/releases/tag/v2.22)
- Docker LAN版：`docker-lan-v2.22/`、ロリポップ版：`release-sources/v2.22/`
- 同じLAN内のみのHTTPテスト環境では、実在の児童・生徒の情報は入力しないでください

## v2.21：カリキュラム作成から1日の流れへ直接移動

カリキュラム生成画面で「生成後、そのまま1日の支援の流れを作成する」を選べます。生成済みカリキュラムからも直接開けます。これまでのPDF転記・保存修正と小学校高学年〜高校生向け利用者用帳票は維持しています。

- [GitHub Release v2.21](https://github.com/kamo0715/ryoiku-install/releases/tag/v2.21)
- ロリポップ向けv2.21完全版・v2.20からの差分ZIP
- Linux AMD64向けLAN専用Dockerテスト版：`docker-lan-v2.21/`

## ファイル構成

- `deploy/`: ロリポップへ配置する最新版v2.21アプリ・CGI・静的ファイルの**ソース**。展開時は `deploy/` の中身をドメインの設置先構造に合わせて配置します
- `patches/v2.18/`, `v2.19/`, `v2.20/`: 変更履歴追跡用の差分ファイル（テキスト部分）
- `tests/`: 配布物に含まれていたローカル検証コード
- `docs/`: 導入・運用・変更履歴の説明
- `update-ryoiku-v2.*.sh`: 過去に使用した更新スクリプト（既存のまま維持）

**重要:** `deploy/` のソースには第三者Python依存パッケージ（`vendor/`）を含めませんが、最新版の新規導入用完全版ZIPは `releases/v2.20/complete_zip_parts/` の30分割ファイルから復元できます。実際の児童データ、DB、`.env`、APIキー等はGit管理しません。復元方法は `releases/v2.20/README.md` を参照してください。

## 新規導入用の完全版ZIPを復元

リポジトリをクローンしたPCで `python3 tools/assemble-v2.20.py` を実行してください。約22MBのZIPを組み立て、SHA-256照合とZIP検査を実施します。**復元されたZIPを既存稼働環境へ無条件で上書きしないでください。**

## 既存環境の更新

v2.19 → v2.20 は `patches/v2.20/` にある3ファイルのみ差し替えます。v2.18以下から飛び越して差分適用しないでください。事前にデータ・設定を安全な場所へバックアップします。詳細は `docs/DEPLOYMENT.md` を参照。

## プライバシー

AI連携時は個人識別情報を必要最小限に置換・抽象化し、支援の意味を保持する設計です。**匿名化を絶対視せず、職員による送信前確認を必須**としてください。実際の児童名・学校名・支援記録や秘密情報をGitへ登録しないでください。

## 版管理

- v2.18: 支援内容の文脈を保持する匿名化・AI送信前確認
- v2.19: 利用者用の「1日の流れ」PDF/Word/Excelを追加
- v2.20: 利用者用帳票を小学校高学年〜高校生向けデザインへ変更

> 本番ロリポップ環境での動作は未検証です。デプロイ前に管理者・職員・本人用表示・帳票・認証・AI送信前確認をテストしてください。

## LAN専用Dockerテスト環境（v2.21）

Linux / AMD64 のUbuntu Serverで、LAN側IPだけに待ち受けるDockerテスト版は [docker-lan-v2.21/README_DOCKER_LAN.md](docker-lan-v2.21/README_DOCKER_LAN.md) を参照してください。ロリポップ用既存環境は変更しません。初回コード・パスワード等はDockerボリュームに保存し、Gitにはコミットしません。**HTTPのため架空データで検証してください。**

- v2.21: カリキュラム生成直後に1日の流れを編集・出力する動線を追加
