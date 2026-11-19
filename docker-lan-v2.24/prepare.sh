#!/usr/bin/env bash
# Restore pinned vendor and exact v2.23 sources, then v2.24 tracked responsive UI overlay.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -f upload_to_domain_root/_private/app/VERSION && -d upload_to_domain_root/_private/vendor ]]; then
  if [[ "$(tr -d '\r\n' < upload_to_domain_root/_private/app/VERSION)" == '2.24' ]]; then
    echo 'Prepared v2.24 app/vendor already available.'
    exit 0
  fi
fi
root="$(cd .. && pwd)"
[[ -f "$root/scripts/build_v223_release.py" && -f "$root/tools/assemble-v2.20.py" ]] || {
  echo 'Use a clone of ryoiku-install or download the complete v2.24 Docker ZIP.' >&2
  exit 1
}
python3 "$root/tools/assemble-v2.20.py"
python3 "$root/scripts/build_v223_release.py" --out "$root/dist/.v223-for-v224"
BASE="$root/dist/.v223-for-v224/ryoiku_lolipop_v2_23_ftp_full.zip" \
SRC="$root/release-sources/v2.24" python3 - <<'PY_OVERLAY'
from pathlib import Path
import os,shutil,zipfile
base=Path(os.environ['BASE']); src=Path(os.environ['SRC']); root=Path.cwd()
if not base.is_file() or not src.is_dir():raise SystemExit('Missing v2.23 or v2.24 release sources')
with zipfile.ZipFile(base) as z:
    for m in z.infolist():
        if not m.filename.startswith('upload_to_domain_root/'):continue
        rel=Path(m.filename)
        if '..' in rel.parts or rel.is_absolute() or ((m.external_attr>>16)&0o170000)==0o120000:
            raise SystemExit('Unsafe base archive path')
    for m in z.infolist():
        if m.filename.startswith('upload_to_domain_root/'):z.extract(m,'.')
base_ver=root/'upload_to_domain_root/_private/app/VERSION'
assert base_ver.read_text().strip()=='2.23',base_ver.read_text()
files=[p for p in src.rglob('*') if p.is_file() and p.name!='README.md']
assert len(files)==21,len(files)
for p in files:
    if p.is_symlink():raise SystemExit('Symlink overlay rejected')
    rel=p.relative_to(src)
    out=root/'upload_to_domain_root'/rel
    out.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(p,out)
assert base_ver.read_text().strip()=='2.24'
assert 'support_save_draft' in (root/'upload_to_domain_root/_private/app/app.py').read_text()
print('Prepared v2.24 app, responsive assets and verified base dependencies')
PY_OVERLAY
