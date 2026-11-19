#!/usr/bin/env python3
"""Build v2.24 from a pinned v2.23 program archive with a source overlay.
On GitHub CI, invokes scripts/build_v223_release.py from the repository.
"""
from pathlib import Path
from hashlib import sha256
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED
import argparse

ROOT=Path(__file__).resolve().parent.parent
VERSION='2.24'
SOURCE=ROOT/'release-sources/v2.24'
FILES=[
 '_private/app/VERSION',
 '_private/app/app.py','_private/app/storage.py','_private/app/day_flow.py','_private/app/exporters.py',
 '_private/app/templates/generate.html','_private/app/templates/day_flow.html','_private/app/templates/child.html',
 '_private/app/templates/plan.html','_private/app/templates/plan_edit.html','_private/app/templates/support_form.html',
 '_private/app/static/app.css',
 '_private/app/static/generate_batch.js','_private/app/static/generate_multi_select.js',
 '_private/app/static/curriculum_workflow.js','_private/app/static/day_flow_audience.js',
 'static/app.css','static/generate_batch.js','static/generate_multi_select.js',
 'static/curriculum_workflow.js','static/day_flow_audience.js',
]

def build(destination:Path,base_archive:Path|None=None):
    destination.mkdir(parents=True,exist_ok=True)
    overlays={'upload_to_domain_root/'+p:(SOURCE/p).read_bytes() for p in FILES}
    assert overlays['upload_to_domain_root/_private/app/VERSION'].strip()==b'2.24'
    assert b'save_support_draft' in overlays['upload_to_domain_root/_private/app/storage.py']
    assert b'data-workflow-choice' in overlays['upload_to_domain_root/_private/app/templates/generate.html']
    if base_archive is None:
        from build_v223_release import build as build_v223
        with TemporaryDirectory(prefix='ryoiku-v223-base-') as t:
            build_v223(Path(t))
            return _package(destination,Path(t)/'ryoiku_lolipop_v2_23_ftp_full.zip',overlays)
    return _package(destination,base_archive,overlays)

def _package(destination:Path,base_archive:Path,overlays:dict):
    full=destination/'ryoiku_lolipop_v2_24_ftp_full.zip'
    patch=destination/'ryoiku_v2_23_to_v2_24_ftp_patch.zip'
    with ZipFile(base_archive) as src,ZipFile(full,'w',ZIP_DEFLATED,compresslevel=7) as dst:
        known=set()
        for info in src.infolist():
            known.add(info.filename)
            dst.writestr(info,overlays.get(info.filename,src.read(info)))
        for key,value in sorted(overlays.items()):
            if key not in known:dst.writestr(key,value)
    with ZipFile(patch,'w',ZIP_DEFLATED,compresslevel=9) as dst:
        for key,value in sorted(overlays.items()):dst.writestr(key.removeprefix('upload_to_domain_root/'),value)
    for zpath in (full,patch):
        with ZipFile(zpath) as z:
            assert z.testzip() is None
            for key,value in overlays.items():
                name=key if zpath==full else key.removeprefix('upload_to_domain_root/')
                assert z.read(name)==value,(zpath,name)
    checks=destination/'SHA256SUMS.txt'
    checks.write_text(''.join(f'{sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in (full,patch)))
    (destination/'RELEASE_NOTES.md').write_text('''# v2.24 — 下書き整理とスマホ・タブレット向けUI改善

- 下書き保存は個別支援計画のみ。本人が入力中の計画は職員ごと・利用者ごとに暗号化保存し、正式な版と区別します。
- 従来の活動計画の `draft` 状態は削除せず `saved` に安全移行。新規生成は完了した活動のみ保存し、職員確認と正式な承認の仕組みを維持します。
- カリキュラム作成は「複数まとめて作る」「1件だけ作る」「保存済みを使う」を切り替える構成。補助項目は必要な場合だけ表示。
- 1日の流れは活動順と開始時刻を中心に、詳細編集を折りたたみ、帳票対象を1つ選んでPDF/Word/Excelを出力。
- ブラウザで360px/390px/820px/1280pxの横はみ出し無し・動作を検証。
- v2.23→v2.24の差分ZIPはロリポップ版専用。Docker版は自己完結ZIPです。事前にDBと暗号鍵をまとめてバックアップしてください。
- LANテスト版はHTTPのため、実在する児童・生徒の個人情報を入力しないでください。
''',encoding='utf-8')
    for p in (full,patch):print(p,p.stat().st_size,sha256(p.read_bytes()).hexdigest())

if __name__=='__main__':
    a=argparse.ArgumentParser()
    a.add_argument('--out',type=Path,required=True)
    a.add_argument('--base-archive',type=Path)
    x=a.parse_args()
    build(x.out,x.base_archive)
