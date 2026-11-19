#!/usr/bin/env python3
"""Build Lolipop v2.23, using exact base and versioned text source overlays."""
from pathlib import Path
from hashlib import sha256
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED
import argparse
from build_v222_release import build as build_v222

ROOT=Path(__file__).resolve().parent.parent
OVERLAY_ROOT=ROOT/'release-sources/v2.23'
FILES=['_private/app/VERSION','_private/app/app.py','_private/app/storage.py',
       '_private/app/templates/generate.html','_private/app/templates/batch_privacy_preview.html',
       'static/generate_batch.js']

def build(out:Path):
    overlays={'upload_to_domain_root/'+p:(OVERLAY_ROOT/p).read_bytes() for p in FILES}
    if overlays['upload_to_domain_root/_private/app/VERSION'].strip()!=b'2.23':
        raise SystemExit('Incorrect v2.23 version file')
    if b'generate_batch_post' not in overlays['upload_to_domain_root/_private/app/app.py']:
        raise SystemExit('Batch generator missing')
    if b'add_plans_batch' not in overlays['upload_to_domain_root/_private/app/storage.py']:
        raise SystemExit('Atomic plan save missing')
    if b'batch-generate-form' not in overlays['upload_to_domain_root/_private/app/templates/generate.html']:
        raise SystemExit('New multi-generating form missing')
    out.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='ryoiku-base-v222-') as t:
        oldroot=Path(t)
        build_v222(oldroot)
        src=oldroot/'ryoiku_lolipop_v2_22_ftp_full.zip'
        full=out/'ryoiku_lolipop_v2_23_ftp_full.zip'
        with ZipFile(src) as zsrc, ZipFile(full,'w',ZIP_DEFLATED,compresslevel=7) as dst:
            known=set()
            for info in zsrc.infolist():
                known.add(info.filename)
                dst.writestr(info,overlays.get(info.filename,zsrc.read(info)))
            for key,val in overlays.items():
                if key not in known:dst.writestr(key,val)
    patch=out/'ryoiku_v2_22_to_v2_23_ftp_patch.zip'
    with ZipFile(patch,'w',ZIP_DEFLATED,compresslevel=9) as z:
        for key,val in overlays.items():
            z.writestr(key.removeprefix('upload_to_domain_root/'),val)
    for path in (full,patch):
        with ZipFile(path) as z:
            if z.testzip():raise SystemExit(f'ZIP corrupted: {path}')
            for name,content in overlays.items():
                if z.read(name if path==full else name.removeprefix('upload_to_domain_root/'))!=content:
                    raise SystemExit(f'Overlay mismatch: {name}')
    (out/'SHA256SUMS.txt').write_text(''.join(
        f'{sha256(path.read_bytes()).hexdigest()}  {path.name}\n' for path in (full,patch)),encoding='utf-8')
    (out/'RELEASE_NOTES.md').write_text('# v2.23 — 複数の新規カリキュラムを一度に生成\n\n- 活動の種類・ジャンル・テーマ・活動時間・配慮事項を個別に選び、新規2〜8件を1回の操作で作成\n- 保存済み計画の事前作成を必要とせず、生成した新規活動を同日の日別編集画面に自動選択\n- 外部AI送信は最大2並列、全件で情報最小化プレビューを確認してから実行\n- AI生成失敗時は一件も登録せず、DB登録は全件を一つのトランザクションで確定\n- Minecraft、ICT・学習・SSTなど同一日に混在可能\n- PDF/Word/Excel、職員/関係機関/利用者用の既存帳票は継続\n- Docker LAN専用HTTPは架空データのみ使用してください\n- ロリポップ差分ZIPはv2.22からの更新専用。DBと暗号化キーをバックアップしてください\n',encoding='utf-8')
    for path in (full,patch):print(path.name,path.stat().st_size,sha256(path.read_bytes()).hexdigest())

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--out',type=Path,required=True)
    build(p.parse_args().out)
