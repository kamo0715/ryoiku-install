#!/usr/bin/env bash
# v2.7 OCR accuracy improvement, self-contained updater for v2.6 only.
# No patient data or secrets in this installer. No Cloudflare/Tailscale changes.
set -Eeuo pipefail
umask 077
EXPECTED_PATCH_SHA256="4e498fa4e8c0c580adc4ce02d057e89665ac0b7ad133d760cd2003a0b198e38c"
EXPECTED_OLD_OCR="d6049be9c4bb9e8eb0565e78558450744d117808b30190288b079c80a2b85433"
EXPECTED_OLD_PDF="949b21d3a84112dad25234997ed37cf332278a7f67a4e1596e87f1608a10f20f"
EXPECTED_OLD_VERSION="8b6f2a818985188f55a3e4e26e239c69a21b70e1306b5231e65694ea4a547128"
EXPECTED_OLD_APP="52b0200c1c68ed294113e1345c436cde32a70489d88cd37867f5ca3c42e41b39"
usage() {
 cat <<'USAGE'
療育カリキュラム作成システム v2.6 -> v2.7（日本語OCR改善）
  bash update-ryoiku-v2.7.sh --verify
  sudo bash update-ryoiku-v2.7.sh --check
  sudo bash update-ryoiku-v2.7.sh --apply
v2.6標準ファイルのみ対象。既存の設定・データ・Cloudflare/Tailscale・3000番には触れません。
原本照合は必須です。スキャンPDF処理は以前より時間を要する場合があります。
USAGE
}
fail() { echo "エラー: $*" >&2; exit 1; }
mode="${1:---check}"
case "$mode" in --verify|--check|--apply) ;; --help|-h) usage;exit 0 ;; *) usage;exit 2 ;; esac
for tool in base64 sha256sum unzip mktemp tar awk; do command -v "$tool" >/dev/null || fail "$tool がありません。"; done
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
base64 -d > "$TMP/patch.zip" <<'RYOIKU_V27_ZIP_B64'
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
RYOIKU_V27_ZIP_B64
actual_sha="$(sha256sum "$TMP/patch.zip" | awk '{print $1}')"
[[ "$actual_sha" == "$EXPECTED_PATCH_SHA256" ]] || fail '内蔵ZIPのSHA256が一致しません。'
unzip -tqq "$TMP/patch.zip" || fail '内蔵ZIPが壊れています。'
if [[ "$mode" == '--verify' ]]; then echo "OK: v2.7更新データの検証成功 SHA256=$actual_sha";exit 0;fi
[[ "$EUID" -eq 0 ]] || fail 'Docker操作はsudoで実行してください。'
for tool in docker curl; do command -v "$tool" >/dev/null || fail "$tool がありません。";done
docker compose version >/dev/null || fail 'Docker Composeが利用できません。'
docker info >/dev/null || fail 'Dockerに接続できません。'
CONTAINER='minecraft-ryoiku-web'
docker container inspect "$CONTAINER" >/dev/null 2>&1 || fail '療育アプリのコンテナが見つかりません。'
SERVICE="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.service" }}' "$CONTAINER")"
[[ "$SERVICE" == 'ryoiku' ]] || fail "別サービスを検出したため中止: $SERVICE"
DEST="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$CONTAINER")"
[[ "$DEST" == /* && -d "$DEST" ]] || fail '療育アプリの作業ディレクトリが見つかりません。'
[[ -f "$DEST/compose.yml" && -f "$DEST/.env" && -d "$DEST/data" ]] || fail '既存の設定/DB/Compose構成がありません。'
[[ "$(tr -d '
' < "$DEST/VERSION")" == '2.6' ]] || fail 'v2.6標準版の更新専用です。'
check_hash() {
 local name="$1" expected="$2" value
 [[ -f "$DEST/$name" && ! -L "$DEST/$name" ]] || fail "既存ファイルがありません: $name"
 value="$(sha256sum "$DEST/$name" | awk '{print $1}')"
 [[ "$value" == "$expected" ]] || fail "既存ファイルが改変されています: $name。上書きを中止しました。"
}
check_hash ocr_import.py "$EXPECTED_OLD_OCR"
check_hash pdf_import.py "$EXPECTED_OLD_PDF"
check_hash VERSION "$EXPECTED_OLD_VERSION"
check_hash app.py "$EXPECTED_OLD_APP"
for path in OCR_QUALITY_v2_7.md tests/ocr_quality_v27.py;do [[ ! -e "$DEST/$path" ]] || fail "すでにファイルが存在します: $path";done
docker compose -f "$DEST/compose.yml" --project-directory "$DEST" config -q || fail '現在のCompose設定が不正です。'
if [[ "$mode" == '--check' ]];then echo "OK: v2.7事前確認のみ完了: $DEST";exit 0;fi
unzip -q "$TMP/patch.zip" -d "$TMP/new"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/var/backups/ryoiku-curriculum/${STAMP}-pre-v27"
mkdir -p "$BACKUP"
chmod 700 /var/backups/ryoiku-curriculum "$BACKUP"
STOPPED=0; CHANGED=0
rollback() {
 local status="$?"
 trap - ERR
 set +e
 echo "更新失敗(終了コード=$status)。旧版の復旧を試みます。" >&2
 if [[ "$STOPPED" == 1 ]];then
  cd "$DEST" || exit "$status"
  if [[ "$CHANGED" == 1 && -f "$BACKUP/code-before-update.tar.gz" ]];then
   rm -f OCR_QUALITY_v2_7.md tests/ocr_quality_v27.py
   tar -xzf "$BACKUP/code-before-update.tar.gz" -C "$DEST"
   docker compose build ryoiku
  fi
  docker compose up -d --no-deps ryoiku
 fi
 echo "バックアップ先: $BACKUP" >&2
 exit "$status"
}
trap rollback ERR
cd "$DEST"
echo '療育アプリのコンテナのみ停止します。'
docker compose stop ryoiku
STOPPED=1
tar -czf "$BACKUP/data-and-env.tar.gz" .env data
tar --exclude='./data' --exclude='./.env' -czf "$BACKUP/code-before-update.tar.gz" .
chmod 600 "$BACKUP"/*.gz
CHANGED=1
for path in ocr_import.py pdf_import.py VERSION OCR_QUALITY_v2_7.md tests/ocr_quality_v27.py;do
 cp -a "$TMP/new/$path" "$DEST/$path"
done
echo '療育アプリのみDocker再ビルドします。'
docker compose build ryoiku
docker compose up -d --no-deps ryoiku
healthy=0
for attempt in $(seq 1 25);do
 code="$(curl -sS --max-time 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/login 2>/dev/null || true)"
 if [[ "$code" == '200' || "$code" == '303' ]];then healthy=1;break;fi
 sleep 2
done
[[ "$healthy" == 1 ]] || fail '更新後の療育アプリが応答しません。'
[[ "$(tr -d '
' < "$DEST/VERSION")" == '2.7' ]] || fail '更新後のバージョンが不一致です。'
trap - ERR
STOPPED=0;CHANGED=0
echo "OK: v2.7更新完了。バックアップ先=$BACKUP"
echo '任意のサンプルテスト: sudo docker exec minecraft-ryoiku-web python tests/ocr_quality_v27.py'
