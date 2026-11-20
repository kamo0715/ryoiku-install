#!/usr/bin/env bash
# Rebuild verified v2.24 base source and apply tracked v2.25 handoff overlay.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -f upload_to_domain_root/_private/app/VERSION && -d upload_to_domain_root/_private/vendor ]]; then
  if [[ "$(tr -d '\r\n' < upload_to_domain_root/_private/app/VERSION)" == '2.25' ]]; then
    echo 'v2.25 app and vendor already prepared.'
    exit 0
  fi
fi
root="$(cd .. && pwd)"
[[ -f "$root/scripts/build_v224_release.py" && -f "$root/tools/assemble-v2.20.py" ]] || {
  echo 'Use the original GitHub repository or download the self-contained v2.25 Docker ZIP.' >&2; exit 1;
}
python3 "$root/tools/assemble-v2.20.py"
python3 "$root/scripts/build_v224_release.py" --out "$root/dist/.v224-for-v225"
SOURCE="$root/dist/.v224-for-v225/ryoiku_lolipop_v2_24_ftp_full.zip" \
OVERLAY="$root/release-sources/v2.25" python3 - <<'PY_EXTRACT'
from pathlib import Path
import os,shutil,zipfile
source=Path(os.environ['SOURCE'])
over=Path(os.environ['OVERLAY'])
with zipfile.ZipFile(source) as z:
  for m in z.infolist():
    if not m.filename.startswith('upload_to_domain_root/'):continue
    dest=Path(m.filename)
    if '..' in dest.parts or dest.is_absolute() or ((m.external_attr>>16)&0o170000)==0o120000:
        raise SystemExit('Unsafe ZIP path')
  for m in z.infolist():
    if m.filename.startswith('upload_to_domain_root/'):
      z.extract(m,'.')
appver=Path('upload_to_domain_root/_private/app/VERSION')
assert appver.read_text().strip()=='2.24'
files=[p for p in over.rglob('*') if p.is_file() and p.name!='README.md']
assert len(files)==8,len(files)
for p in files:
  if p.is_symlink():raise SystemExit('Symlinks not allowed')
  dst=Path('upload_to_domain_root')/p.relative_to(over)
  dst.parent.mkdir(parents=True,exist_ok=True)
  shutil.copy2(p,dst)
assert appver.read_text().strip()=='2.25'
print('Prepared v2.25 app with separate handoff module and v2.24 vendor')
PY_EXTRACT
