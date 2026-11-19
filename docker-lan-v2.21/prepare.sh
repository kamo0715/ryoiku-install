#!/usr/bin/env bash
# Reconstruct v2.21 sources from verified v2.20 binary dependencies and tracked v2.21 source files.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -f upload_to_domain_root/_private/app/VERSION && -d upload_to_domain_root/_private/vendor ]]; then
  if [[ "$(tr -d '\r\n' < upload_to_domain_root/_private/app/VERSION)" == '2.21' ]]; then
    echo 'v2.21 app/vendor already present; keeping them unchanged.'
    exit 0
  fi
fi
root="$(cd .. && pwd)"
[[ -f "$root/tools/assemble-v2.20.py" ]] || { echo 'Run from a git clone of ryoiku-install or use the self-contained v2.21 ZIP' >&2; exit 1; }
python3 "$root/tools/assemble-v2.20.py"
SOURCE="$root/releases/v2.20/ryoiku_lolipop_student_schedule_v2_20_ftp_full.zip" python3 - <<'PYINNER'
from pathlib import Path
import hashlib,os,shutil,zipfile
root=Path.cwd().parent
source=Path(os.environ['SOURCE'])
if hashlib.sha256(source.read_bytes()).hexdigest()!='89d3db9fd235f15705ed7cab7e8787df8f8b852d9c009797b991dfc6311dfafe':
    raise SystemExit('Base archive SHA256 mismatch')
with zipfile.ZipFile(source) as z:
  for m in z.infolist():
    if not m.filename.startswith('upload_to_domain_root/'):continue
    dest=Path(m.filename)
    if '..' in dest.parts or dest.is_absolute() or ((m.external_attr>>16)&0o170000)==0o120000:
        raise SystemExit('Unsafe archive entry')
  for m in z.infolist():
    if m.filename.startswith('upload_to_domain_root/'):
      z.extract(m,'.')
for sub in ['VERSION','app.py','templates/generate.html','templates/ai_privacy_preview.html','templates/support_form.html']:
  src=root/'release-sources/v2.21/_private/app'/sub
  dst=Path('upload_to_domain_root/_private/app')/sub
  if not src.is_file():raise SystemExit(f'Missing v2.21 overlay: {src}')
  shutil.copy2(src,dst)
assert Path('upload_to_domain_root/_private/app/VERSION').read_text().strip()=='2.21'
assert 'after_generate' in Path('upload_to_domain_root/_private/app/app.py').read_text()
print('Prepared v2.21 app + pinned v2.20 vendor dependencies')
PYINNER
