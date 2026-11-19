#!/usr/bin/env python3
"""Rebuild exact v2.21 distribution from checksum-pinned v2.20 vendor and fixed v2.21 source overlay.
Never read or include child data, SQLite DB, secrets or .env files.
"""
from pathlib import Path
from hashlib import sha256
import argparse,zipfile

ROOT=Path(__file__).resolve().parent.parent
SOURCE=ROOT/'releases/v2.20/ryoiku_lolipop_student_schedule_v2_20_ftp_full.zip'
OVERLAY=ROOT/'release-sources/v2.21/_private/app'
EXPECTED_BASE_SHA='89d3db9fd235f15705ed7cab7e8787df8f8b852d9c009797b991dfc6311dfafe'
CHANGES=['VERSION','app.py','templates/generate.html','templates/ai_privacy_preview.html','templates/support_form.html']

def build(destination):
    if not SOURCE.is_file() or sha256(SOURCE.read_bytes()).hexdigest()!=EXPECTED_BASE_SHA:
        raise SystemExit('Missing/mismatched pinned base v2.20 distribution; run tools/assemble-v2.20.py')
    overlays={f'upload_to_domain_root/_private/app/{r}':(OVERLAY/r).read_bytes() for r in CHANGES}
    if overlays['upload_to_domain_root/_private/app/VERSION'].strip()!=b'2.21':
        raise SystemExit('v2.21 source version mismatch')
    if b'after_generate' not in overlays['upload_to_domain_root/_private/app/app.py']:
        raise SystemExit('Missing direct generation workflow')
    if b'action="/children/{{child.id}}/support/new"' not in overlays['upload_to_domain_root/_private/app/templates/support_form.html']:
        raise SystemExit('PDF import save fix missing')
    destination.mkdir(parents=True,exist_ok=True)
    full=destination/'ryoiku_lolipop_v2_21_ftp_full.zip'
    with zipfile.ZipFile(SOURCE) as zin,zipfile.ZipFile(full,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=7) as zout:
        for info in zin.infolist():
            data=overlays.get(info.filename)
            if data is None:data=zin.read(info)
            zout.writestr(info,data)
    with zipfile.ZipFile(full) as z:
        if z.testzip() is not None:raise SystemExit('Corrupted rebuilt full ZIP')
        for name,value in overlays.items():
            if z.read(name)!=value: raise SystemExit(f'Missing/changed overlay {name}')
    patch=destination/'ryoiku_v2_20_to_v2_21_ftp_patch.zip'
    with zipfile.ZipFile(patch,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,value in overlays.items():z.writestr(name.removeprefix('upload_to_domain_root/'),value)
    with zipfile.ZipFile(patch) as z:
        if z.testzip():raise SystemExit('Corrupted patch ZIP')
    manifest=destination/'SHA256SUMS.txt'
    manifest.write_text('\n'.join(f'{sha256(p.read_bytes()).hexdigest()}  {p.name}' for p in (full,patch))+'\n')
    (destination/'RELEASE_NOTES.md').write_text('''# v2.21 — カリキュラム作成画面から1日の流れを作成

- 新規カリキュラム生成後、1日の流れ編集画面へ直接移動できます。
- 作成済みカリキュラムからも同じ画面で1日の流れを編集できます。
- 複数活動・休憩・時刻の編集、職員/関係機関/利用者用PDF・Word・Excelは従来どおり。
- v2.20のPDF転記保存修正、AI送信前匿名化確認、Docker LANアクセス制限を保持。
- 完全版はv2.20の検証済みバイナリ依存ライブラリとv2.21の固定ソースから再構成。
- Docker版は別の自己完結ZIP、Linux AMD64用。テスト用HTTPのため実データは使用しないでください。
- 差分ZIPはv2.20からv2.21への更新専用。事前にDB・秘密鍵のバックアップ必須。
''',encoding='utf-8')
    for p in (full,patch):print(p.name,len(p.read_bytes()),sha256(p.read_bytes()).hexdigest())

if __name__=='__main__':
    arg=argparse.ArgumentParser();arg.add_argument('--out',type=Path,required=True)
    build(arg.parse_args().out)
