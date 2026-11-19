#!/usr/bin/env python3
"""Build v2.22 full Lolipop distribution and v2.21-to-v2.22 patch.
Original v2.20 binary/vendor is checksum verified by build_v221_release.
No user data or host environment secrets are packaged.
"""
from pathlib import Path
from hashlib import sha256
from tempfile import TemporaryDirectory
from zipfile import ZipFile,ZIP_DEFLATED
import argparse
from build_v221_release import build as build_v221

ROOT=Path(__file__).resolve().parent.parent
SRC=ROOT/'release-sources/v2.22'
FILES=['_private/app/VERSION','_private/app/app.py',
       '_private/app/templates/generate.html',
       '_private/app/templates/day_flow.html',
       '_private/app/templates/ai_privacy_preview.html',
       'static/generate_multi_select.js']


def build(out:Path):
    overlays={'upload_to_domain_root/'+name:(SRC/name).read_bytes() for name in FILES}
    if overlays['upload_to_domain_root/_private/app/VERSION'].strip()!=b'2.22':
        raise SystemExit('v2.22 version source mismatch')
    if b'child_day_flow_selection' not in overlays['upload_to_domain_root/_private/app/app.py']:
        raise SystemExit('Multiple curriculum selection route is absent')
    if b'curriculum-multi-form' not in overlays['upload_to_domain_root/_private/app/templates/generate.html']:
        raise SystemExit('Multiple curriculum selector UI is absent')
    if b'combine_plan_ids' not in overlays['upload_to_domain_root/_private/app/templates/ai_privacy_preview.html']:
        raise SystemExit('External AI privacy preview does not retain selected curricula')
    out.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='ryoiku-v221-source-') as t:
        tmp=Path(t)
        build_v221(tmp)
        source=tmp/'ryoiku_lolipop_v2_21_ftp_full.zip'
        full=out/'ryoiku_lolipop_v2_22_ftp_full.zip'
        with ZipFile(source) as zsrc, ZipFile(full,'w',ZIP_DEFLATED,compresslevel=7) as zout:
            known=set()
            for info in zsrc.infolist():
                known.add(info.filename)
                zout.writestr(info,overlays.get(info.filename,zsrc.read(info)))
            for name,data in overlays.items():
                if name not in known:
                    zout.writestr(name,data)
    patch=out/'ryoiku_v2_21_to_v2_22_ftp_patch.zip'
    with ZipFile(patch,'w',ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in overlays.items():
            z.writestr(name.removeprefix('upload_to_domain_root/'),data)
    for f in (full,patch):
        with ZipFile(f) as z:
            if z.testzip():raise SystemExit(f'Corrupted {f}')
            for name,data in overlays.items():
                if z.read(name if f==full else name.removeprefix('upload_to_domain_root/'))!=data:
                    raise SystemExit(f'Overlay missing: {name}')
    sums=out/'SHA256SUMS.txt'
    sums.write_text(''.join(f'{sha256(f.read_bytes()).hexdigest()}  {f.name}\n' for f in (full,patch)),encoding='utf-8')
    (out/'RELEASE_NOTES.md').write_text('''# v2.22：1日複数カリキュラム選択\n\n- 「カリキュラムを生成」画面で保存済みの複数活動をまとめて選び、日別編集へ進めます（最大8件）。\n- 新しく生成した活動に、保存済みの活動を最大7件追加できます。\n- 選択順の編集、休憩・移動の挿入、時刻自動計算。\n- 職員用・関係機関用・利用者用PDF/Word/Excelを維持。\n- 別利用者の計画を拒否し、件数上限と重複入力を検証。\n- 外部AIへの送信前匿名化確認を維持。計画IDはAIへ送信しません。\n- Docker LAN専用HTTPは架空データでのみ利用してください。\n- v2.21からの差分ZIPはDB・秘密鍵バックアップ後に利用してください。\n''',encoding='utf-8')
    for f in (full,patch):
        print(f.name, f.stat().st_size, sha256(f.read_bytes()).hexdigest())

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--out',type=Path,required=True)
    build(p.parse_args().out)
