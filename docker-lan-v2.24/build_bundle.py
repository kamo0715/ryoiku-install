#!/usr/bin/env python3
"""Create an audited, self-contained Docker LAN test ZIP from v2.24 sources."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import argparse, hashlib, os, sys

ROOT=Path(__file__).resolve().parent
APP=ROOT/'upload_to_domain_root/_private/app/VERSION'
EXCLUDED={'.env','INITIAL_ADMIN_CODE.txt','.git','__pycache__','.pytest_cache','.mypy_cache'}
NAME='ryoiku-v2.24-docker-lan-test'

def package(out:Path):
    if not APP.is_file() or APP.read_text(encoding='utf-8').strip()!='2.24':
        raise SystemExit('Exact v2.24 source is required: run ./prepare.sh first')
    if not (ROOT/'upload_to_domain_root/_private/vendor/fastapi').is_dir():
        raise SystemExit('v2.24 vendor dependencies missing')
    parts=['Dockerfile','compose.yaml','.env.example','.dockerignore','.gitignore',
           'install-lan-test.sh','remove-old-ryoiku.sh','fix-pdf-save-local.sh','prepare.sh','README_DOCKER_LAN.md','build_bundle.py']
    files=[ROOT/x for x in parts]
    files.extend(p for folder in ('docker','tests_docker','upload_to_domain_root')
                 for p in (ROOT/folder).rglob('*') if p.is_file())
    files=[p for p in files if not (set(p.parts)&EXCLUDED)
           and not p.name.endswith(('.pyc','.pyo','.sqlite3','.db','.env','.log'))]
    out.parent.mkdir(parents=True,exist_ok=True)
    with ZipFile(out,'w',ZIP_DEFLATED,compresslevel=7) as z:
        for p in sorted(set(files)):
            rel=p.relative_to(ROOT)
            # Ensure the self-contained ZIP has the fixed template, not archived v2.24's old form.
            if rel.as_posix() == 'upload_to_domain_root/_private/app/templates/support_form.html':
                z.write(ROOT/'docker/overrides/support_form.html',arcname=f'{NAME}/{rel.as_posix()}')
            else:
                z.write(p,arcname=f'{NAME}/{rel.as_posix()}')
        bad=z.testzip()
        if bad:raise SystemExit(f'ZIP corrupted entry: {bad}')
    with ZipFile(out) as z:
        assert z.testzip() is None
        names=z.namelist()
        assert not any('/.env' in name and not name.endswith('.env.example') for name in names)
        assert not any('INITIAL_ADMIN_CODE' in name for name in names)
        assert any(name.endswith('app/VERSION') for name in names)
    h=hashlib.sha256(out.read_bytes()).hexdigest()
    print(f'Created: {out} ({out.stat().st_size:,} bytes)')
    print(f'SHA256: {h}')
    return h

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT.parent/(NAME+'.zip'))
    args=parser.parse_args()
    package(args.output.resolve())
