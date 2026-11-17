#!/usr/bin/env bash
# v2.8 field attribution: v2.7-only update, download checksum-pinned source files.
# No change to other Docker services, Cloudflare, Tailscale, compose.yml, .env or data.
set -Eeuo pipefail
umask 077
MODE="--check"
if [[ $# -gt 0 ]];then MODE="$1";fi
case "$MODE" in --verify|--check|--apply) ;; --help|-h)
  echo 'Usage: bash update-ryoiku-v2.8.sh --verify | sudo bash update-ryoiku-v2.8.sh --check | sudo bash update-ryoiku-v2.8.sh --apply'; exit 0;;
*) echo 'Unknown option' >&2; exit 2;; esac
fail(){ echo "エラー: $*" >&2; exit 1; }
for cmd in wget sha256sum mktemp python3 tar awk; do command -v "$cmd" >/dev/null || fail "$cmd が見つかりません。"; done
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# Pin to the reviewed, immutable repository commit rather than mutable main.
BASE='https://raw.githubusercontent.com/kamo0715/ryoiku-install/60d2bf28aa74f9bdd6bdd3309697e2ede3860d8e/v2.8'
wget -q --timeout=15 --tries=3 -O "$TMP/support_analyzer.py" "$BASE/support_analyzer.py" || fail '解析エンジンをGitHubから取得できません。'
wget -q --timeout=15 --tries=3 -O "$TMP/apply_patch.py" "$BASE/apply_patch.py" || fail '更新パッチをGitHubから取得できません。'
echo 'c4619b6048696f621997c454a20b28b71658b5259dc6b6b17c46d5d252f4b1d2  '"$TMP"'/support_analyzer.py' | sha256sum -c - || fail '解析エンジンのSHA-256が一致しません。'
echo 'a1b293a0d7f42cde2c5007899eefe4670d0d07a0d2b283ef1968de5b24b50524  '"$TMP"'/apply_patch.py' | sha256sum -c - || fail '更新パッチのSHA-256が一致しません。'
python3 - "$TMP" <<'PY'
import ast,sys,pathlib
folder=pathlib.Path(sys.argv[1])
for name in ('support_analyzer.py','apply_patch.py'):
 ast.parse((folder/name).read_text(encoding='utf8'),filename=name)
PY
if [[ "$MODE" == '--verify' ]];then echo 'OK: v2.8公開配布ファイルの検証完了';exit 0;fi
[[ "$EUID" -eq 0 ]] || fail 'Docker更新にはsudoが必要です。'
for cmd in docker curl;do command -v "$cmd" >/dev/null || fail "$cmd がありません。";done
docker compose version >/dev/null || fail 'Docker Composeが使えません。'
docker info >/dev/null || fail 'Dockerが稼働していません。'
CONTAINER='minecraft-ryoiku-web'
docker inspect "$CONTAINER" >/dev/null 2>&1 || fail '療育アプリのコンテナが見つかりません。'
SERVICE="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.service" }}' "$CONTAINER")"
[[ "$SERVICE" == 'ryoiku' ]] || fail "想定外のサービスです: $SERVICE"
DEST="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$CONTAINER")"
[[ "$DEST" == /* && -d "$DEST" ]] || fail '療育アプリの配置先が見つかりません。'
[[ -f "$DEST/compose.yml" && -f "$DEST/.env" && -d "$DEST/data" ]] || fail '設定またはデータ領域が見つかりません。'
[[ "$(tr -d '\r\n' < "$DEST/VERSION")" == '2.7' ]] || fail 'この更新はv2.7専用です。'
check_hash(){
 local file="$1" expected="$2" actual
 [[ -f "$DEST/$file" && ! -L "$DEST/$file" ]] || fail "既存ファイルが存在しません: $file"
 actual="$(sha256sum "$DEST/$file" | awk '{print $1}')"
 [[ "$actual" == "$expected" ]] || fail "既存ファイルの変更を検出: $file。安全のため中止。"
}
check_hash ocr_import.py f0d42c182b5f0e0f2ed6c71dba753197ab85b9b59ceac3aada1ef065c1f80f5f
check_hash app.py 52b0200c1c68ed294113e1345c436cde32a70489d88cd37867f5ca3c42e41b39
check_hash templates/support_form.html e74c617d68219a81fb3834e96f8be43d5898d63fbae16d972f55c3ea88699b99
check_hash VERSION 884784765bb9a529058c24f63946a7e21a20394a4502e6db91f97e7e3fd9dda5
[[ ! -e "$DEST/support_analyzer.py" ]] || fail 'すでにsupport_analyzer.pyが存在しています。中止。'
docker compose -f "$DEST/compose.yml" --project-directory "$DEST" config -q || fail '既存Docker Composeの構成チェックに失敗。'
if [[ "$MODE" == '--check' ]];then echo "OK: v2.8事前チェック合格。変更なし: $DEST";exit 0;fi
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/var/backups/ryoiku-curriculum/"$STAMP"-pre-v28"
mkdir -p "$BACKUP"
chmod 700 /var/backups/ryoiku-curriculum "$BACKUP"
STOPPED=0;CHANGED=0
rollback(){
 local status="$?";trap - ERR;set +e
 echo "更新に失敗しました（終了コード=$status）。v2.7への復旧を試みます。" >&2
 if [[ "$STOPPED" == 1 ]];then
  cd "$DEST" || exit "$status"
  if [[ "$CHANGED" == 1 && -f "$BACKUP/code-before-update.tar.gz" ]];then
   rm -f support_analyzer.py
   tar -xzf "$BACKUP/code-before-update.tar.gz" -C "$DEST"
   docker compose build ryoiku
  fi
  docker compose up -d --no-deps ryoiku
 fi
 echo "バックアップ: $BACKUP" >&2
 exit "$status"
}
trap rollback ERR
cd "$DEST"
echo '療育アプリのみ停止します。'
docker compose stop ryoiku
STOPPED=1
tar -czf "$BACKUP/data-and-env.tar.gz" .env data
tar --exclude='./data' --exclude='./.env' -czf "$BACKUP/code-before-update.tar.gz" .
chmod 600 "$BACKUP"/*.gz
CHANGED=1
cp -a "$TMP/support_analyzer.py" "$DEST/support_analyzer.py"
python3 "$TMP/apply_patch.py" "$DEST"
# Confirm the result matches the tested v2.8 program byte-for-byte.
check_hash ocr_import.py d02f3ca5bbc0bd2eba0f6bd0b0c57736591d4d34156710a3b96facdecc518c76
check_hash app.py bf0fd827ef3b46c974f000202c70125d5a6882d42f9849806863f72757f5fbb6
check_hash templates/support_form.html 64bc0680f02379633a977bd6e365fdbc80ecf1600aee9a72cfcbd8d41122d72a
check_hash VERSION df5b47311873a4388b15a71ae9846e61cd9cc59d61d37623ed735425a49b1fd0
docker compose build ryoiku
docker compose up -d --no-deps ryoiku
READY=0
for attempt in $(seq 1 25);do
 CODE="$(curl -sS --max-time 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/login 2>/dev/null || true)"
 if [[ "$CODE" == '200' || "$CODE" == '303' ]];then READY=1;break;fi
 sleep 2
done
[[ "$READY" == 1 ]] || fail '更新後の療育アプリが応答しません。'
docker exec "$CONTAINER" python -c "from ocr_import import parse_support_text; d,_,_,_=parse_support_text('長期目標：協力する\\n短期目標：挨拶する'); assert d.get('long_goal') and d.get('short_goal'); print('PASS: 原文解析')" || fail '更新後の原文解析テストに失敗しました。'
trap - ERR
STOPPED=0;CHANGED=0
echo "OK: v2.8アップデート完了。バックアップ先: $BACKUP"
