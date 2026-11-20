#!/usr/bin/env python3
"""Build v2.25 Lolipop full and v2.24->v2.25 patch using tracked source.
No child records, secrets, DB or local .env files are ever packaged.
"""
from pathlib import Path
from hashlib import sha256
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED
import argparse
ROOT=Path(__file__).resolve().parent.parent
OVER=ROOT/'release-sources/v2.25'
FILES=[
 '_private/app/VERSION','_private/app/app.py','_private/app/storage.py',
 '_private/app/templates/child.html','_private/app/templates/child_delete.html',
 '_private/app/templates/handoff.html',
 '_private/app/static/app.css','static/app.css',
]

def build(out:Path,base_archive:Path|None=None):
    overlays={'upload_to_domain_root/'+p:(OVER/p).read_bytes() for p in FILES}
    assert overlays['upload_to_domain_root/_private/app/VERSION'].strip()==b'2.25'
    assert b'add_handoff' in overlays['upload_to_domain_root/_private/app/storage.py']
    assert b'child_handoff_page' in overlays['upload_to_domain_root/_private/app/app.py']
    out.mkdir(parents=True,exist_ok=True)
    if base_archive is None:
        from build_v224_release import build as build_previous
        with TemporaryDirectory(prefix='ryoiku-v224-') as temp:
            build_previous(Path(temp))
            return build(out,Path(temp)/'ryoiku_lolipop_v2_24_ftp_full.zip')
    full=out/'ryoiku_lolipop_v2_25_ftp_full.zip'
    patch=out/'ryoiku_v2_24_to_v2_25_ftp_patch.zip'
    with ZipFile(base_archive) as original,ZipFile(full,'w',ZIP_DEFLATED,compresslevel=7) as target:
        if original.read('upload_to_domain_root/_private/app/VERSION').strip()!=b'2.24':
            raise SystemExit('Expected v2.24 base archive')
        present=set()
        for info in original.infolist():
            present.add(info.filename)
            target.writestr(info,overlays.get(info.filename,original.read(info)))
        for name,value in sorted(overlays.items()):
            if name not in present:target.writestr(name,value)
    with ZipFile(patch,'w',ZIP_DEFLATED,compresslevel=9) as target:
        for name,value in sorted(overlays.items()):
            target.writestr(name.removeprefix('upload_to_domain_root/'),value)
    for path in (full,patch):
        with ZipFile(path) as z:
            if z.testzip():raise SystemExit(f'Broken ZIP: {path}')
            for name,value in overlays.items():
                target=name if path==full else name.removeprefix('upload_to_domain_root/')
                if z.read(target)!=value:raise SystemExit(f'Version source mismatch: {name}')
    (out/'SHA256SUMS.txt').write_text(''.join(
        f'{sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in (full,patch)))
    (out/'RELEASE_NOTES.md').write_text("""# v2.25 — 生徒ごとの独立した引き継ぎ情報

- 生徒情報に「引き継ぎ情報」を追加。カリキュラム・個別支援計画の項目とは分離
- 「いま取り組んでいること」「どこまで進んだか」「次回すること」「配慮・申し送り」を確認・更新
- 状態の選択・最終更新者と更新日時（日本時間）・過去の全履歴のページ表示
- 記録本文は暗号化。生徒ごとの閲覧制限、CSRF検証、変更衝突の検出
- 下書きは個別支援計画だけ。引き継ぎ情報は更新時のみ保存、活動記録は増やさない
- 旧データ・Dockerボリュームは変更・削除せず、起動時にテーブルを自動追加
- ロリポップ v2.24→v2.25差分はv2.24専用。更新前にDBと暗号鍵をバックアップ
- Docker LANテスト版はHTTP通信のため架空データだけを使用してください
""",encoding='utf-8')
    for f in (full,patch):print(f.name,f.stat().st_size,sha256(f.read_bytes()).hexdigest())

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--base-archive',type=Path)
    args=parser.parse_args()
    build(args.out,args.base_archive)
