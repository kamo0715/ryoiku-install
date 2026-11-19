#!/usr/bin/env python3
"""Create historical complete FTP ZIPs from preserved source and versioned vendor ZIP.

Requires the verified original v2.20 full ZIP reconstructed by tools/assemble-v2.20.py.
For v2.11-v2.19 all original file contents (including vendored modules) are preserved;
container format and timestamps may differ. v2.20 is copied byte-identically.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'release-sources'
VENDOR_PREFIX = 'upload_to_domain_root/_private/vendor/'


def write_member(z: zipfile.ZipFile, name: str, content: bytes):
    info = zipfile.ZipInfo(name, date_time=(2026, 11, 19, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    z.writestr(info, content, compresslevel=7)


def build(version: str, vendor_source: Path, out_dir: Path, metadata: dict):
    if version not in metadata or not version.startswith('v2.'):
        raise ValueError('Unknown version '+version)
    out_dir.mkdir(parents=True, exist_ok=True)
    original = metadata[version]
    snapshot = SRC / original['snapshot']
    original_version = version.removeprefix('v')
    allowlist_path = SRC / (version + '.vendor_paths.txt')
    allowlist = set(allowlist_path.read_text(encoding='utf-8').splitlines()) if allowlist_path.exists() else None
    out_file = out_dir / f'ryoiku_lolipop_{version.replace(".", "_")}_ftp_full_rebuilt.zip'

    if version == 'v2.20':
        # The original ZIP is already stored byte-identically as Git binary parts.
        out_file = out_dir / original['original_filename']
        shutil.copyfile(vendor_source, out_file)
    else:
        included = set()
        with zipfile.ZipFile(vendor_source) as vendor, tarfile.open(snapshot, 'r:gz') as source, zipfile.ZipFile(out_file, 'w') as dest:
            for item in source.getmembers():
                name = item.name
                parsed = PurePosixPath(name)
                if (not item.isfile()) or parsed.is_absolute() or '..' in parsed.parts or name in included:
                    raise ValueError('Invalid snapshot entry: '+name)
                write_member(dest, name, source.extractfile(item).read())
                included.add(name)
            for item in vendor.infolist():
                name = item.filename
                if not name.startswith(VENDOR_PREFIX) or item.is_dir() or name.endswith('/vendor/.htaccess'):
                    continue
                if allowlist is not None and name not in allowlist:
                    continue
                if name in included:
                    continue
                write_member(dest, name, vendor.read(item))
                included.add(name)
            if allowlist is not None and not allowlist.issubset(included):
                raise RuntimeError('Missing pinned vendor paths: '+str(sorted(allowlist - included)[:5]))

    with zipfile.ZipFile(out_file) as check:
        if check.testzip() is not None:
            raise RuntimeError('Bad archive: '+str(out_file))
        version_file = 'upload_to_domain_root/_private/app/VERSION'
        if check.read(version_file).decode().strip() != original_version:
            raise RuntimeError('Version mismatch '+version)
        if VENDOR_PREFIX+'fastapi/__init__.py' not in check.namelist():
            raise RuntimeError('Missing dependencies')
    sha = hashlib.sha256(out_file.read_bytes()).hexdigest()
    (out_dir/'SHA256SUMS.txt').write_text(f'{sha}  {out_file.name}\n', encoding='utf-8')
    notes = (
        f'### 療育カリキュラム管理 {version} — ロリポップ用完全版\n\n'
        + ('保存済みオリジナルの完全版ZIPをSHA-256で照合して再構成したものです。\n\n'
           if version=='v2.20' else
           '保存済みの当該バージョンのアプリ本体に、保存済みv2.20完全版と同一の共通ライブラリを組み合わせた再構成ZIPです。'
           'ファイル内容の照合は行っていますが、ZIPメタデータ・順序等が異なるため元のZIPとバイト単位では一致しません。\n\n')
        + f'元ファイル名: `{original["original_filename"]}`\n\n'
        + f'元ZIPのSHA-256: `{original["original_sha256"]}`\n\n'
        + '**新規導入用の完全版です。既存稼働環境へ無条件に上書きせず、適用元の版が一致する差分を使用してください。**\n'
        + '利用者の実データ、DB、APIキー、秘密鍵は配布していません。\n'
    )
    (out_dir/'RELEASE_NOTES.md').write_text(notes, encoding='utf-8')
    print(f'Verified {version}: {out_file} SHA256={sha}')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--vendor-zip',type=Path,required=True,help='verified complete v2.20 original archive')
    parser.add_argument('--out',type=Path,default=Path('dist/full'))
    parser.add_argument('--version',action='append',help='version(s) to build, defaults to all available')
    args=parser.parse_args()
    metadata=json.loads((SRC/'manifest.json').read_text(encoding='utf-8'))
    versions=args.version or sorted(metadata,key=lambda x:int(x.split('.')[-1]))
    for version in versions:
        build(version,args.vendor_zip,args.out/version,metadata)

if __name__=='__main__':main()