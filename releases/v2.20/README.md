# v2.20 配布ファイル

最新の小学校高学年〜高校生向け療育カリキュラム管理アプリ。

## 既存環境の差分更新

`ryoiku_v2_20_student_schedule_ftp_patch.zip` は **v2.19 → v2.20 専用**です。更新前にサイトとDB、設定・APIキーを安全な場所へバックアップしてください。

## 新規導入用 完全版ZIP（約22.6MB）

GitHub接続時のファイルサイズ制約を避けるため、完全版ZIPの同一バイト列を `complete_zip_parts/part_000.bin` 〜 `part_029.bin` に分けて保持しています。

リポジトリを `git clone` したフォルダで実行：

```sh
python3 tools/assemble-v2.20.py
```

出力先：

```
releases/v2.20/ryoiku_lolipop_student_schedule_v2_20_ftp_full.zip
```

ツールはZIPのSHA-256・サイズ・内部整合性を検査します。

- SHA-256：`89d3db9fd235f15705ed7cab7e8787df8f8b852d9c009797b991dfc6311dfafe`
- サイズ：22,580,402 bytes
- Python以外の追加依存なし

**新規導入用ZIPは既存の稼働中サイトへ丸ごと上書きしないこと。** 保存済み利用者データや設定が損なわれる可能性があります。ロリポップでの実機検証は未完了です。
