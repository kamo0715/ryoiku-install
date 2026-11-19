#!/usr/bin/env bash
# Restore exact v2.20 binary libs, then sequential v2.21 and v2.23 sources.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -f upload_to_domain_root/_private/app/VERSION && -d upload_to_domain_root/_private/vendor ]];then
  if [[ "$(tr -d '\r\n' < upload_to_domain_root/_private/app/VERSION)" == 2.23 ]];then
    echo 'Prepared v2.23 sources and vendor already present.'
    exit 0
  fi
fi
root="$(cd .. && pwd)"
[[ -f "$root/tools/assemble-v2.20.py" ]] || { echo 'Run in ryoiku-install repo or download the full v2.23 Docker ZIP.' >&2; exit 1; }
python3 "$root/tools/assemble-v2.20.py"
SOURCE="$root/releases/v2.20/ryoiku_lolipop_student_schedule_v2_20_ftp_full.zip" python3 - <<'PYINNER'
from pathlib import Path
import hashlib,os,shutil,zipfile
root=Path.cwd().parent
source=Path(os.environ['SOURCE'])
if hashlib.sha256(source.read_bytes()).hexdigest()!='89d3db9fd235f15705ed7cab7e8787df8f8b852d9c009797b991dfc6311dfafe':
    raise SystemExit('Pinned base SHA256 mismatch. No extraction performed.')
with zipfile.ZipFile(source) as z:
    chosen=[m for m in z.infolist() if m.filename.startswith('upload_to_domain_root/')]
    for m in chosen:
        dest=Path(m.filename)
        if '..' in dest.parts or dest.is_absolute() or ((m.external_attr>>16)&0o170000)==0o120000:
            raise SystemExit('Unsafe archive path')
    for m in chosen:z.extract(m,'.')
for sub in ['VERSION','app.py','templates/generate.html','templates/ai_privacy_preview.html','templates/support_form.html']:
    src=root/'release-sources/v2.21/_private/app'/sub
    dst=Path('upload_to_domain_root/_private/app')/sub
    if not src.is_file():raise SystemExit(f'Missing v2.21 overlay: {src}')
    shutil.copy2(src,dst)
for sub in ['VERSION','app.py','templates/generate.html','templates/day_flow.html','templates/ai_privacy_preview.html']:
    src=root/'release-sources/v2.22/_private/app'/sub
    dst=Path('upload_to_domain_root/_private/app')/sub
    if not src.is_file():raise SystemExit(f'Missing v2.22 overlay: {src}')
    shutil.copy2(src,dst)
for sub in ['generate_multi_select.js']:
    src=root/'release-sources/v2.22/static'/sub
    dst=Path('upload_to_domain_root/static')/sub
    if not src.is_file():raise SystemExit(f'Missing v2.22 static asset: {src}')
    shutil.copy2(src,dst)
assert Path('upload_to_domain_root/_private/app/VERSION').read_text().strip()=='2.22'
assert 'child_day_flow_selection' in Path('upload_to_domain_root/_private/app/app.py').read_text()
print('Verified v2.20 vendor + v2.21 / v2.22 app overlays')
PYINNER

# Apply v2.23 additions (atomic multi-new-curriculum creation).
python3 - <<'PY_V223'
from pathlib import Path
from shutil import copy2
root=Path.cwd().parent
for name in ('VERSION','app.py','storage.py','templates/generate.html','templates/batch_privacy_preview.html'):
    src=root/'release-sources/v2.23/_private/app'/name
    dest=Path('upload_to_domain_root/_private/app')/name
    if not src.is_file():raise SystemExit(f'Missing v2.23 source: {src}')
    dest.parent.mkdir(parents=True,exist_ok=True)
    copy2(src,dest)
for name in ('generate_batch.js',):
    src=root/'release-sources/v2.23/static'/name
    dest=Path('upload_to_domain_root/static')/name
    if not src.is_file():raise SystemExit(f'Missing v2.23 static: {src}')
    copy2(src,dest)
assert Path('upload_to_domain_root/_private/app/VERSION').read_text().strip()=='2.23'
assert 'generate_batch_post' in Path('upload_to_domain_root/_private/app/app.py').read_text()
print('Prepared v2.23 app + locked v2.20 vendor, sequential version overlays')
PY_V223
