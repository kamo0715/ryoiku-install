#!/usr/bin/env bash
# Retrieve & verify exact v2.20 release ZIP stored in the parent repository.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -f upload_to_domain_root/_private/app/VERSION && -d upload_to_domain_root/_private/vendor ]];then
  [[ "$(tr -d '\r\n' < upload_to_domain_root/_private/app/VERSION)" == '2.20' ]] || { echo 'Unexpected existing app version' >&2;exit 1; }
  echo 'v2.20 app/vendor already extracted. Nothing was overwritten.'
  exit 0
fi
root="$(cd .. && pwd)"
[[ -f "$root/tools/assemble-v2.20.py" ]] || { echo 'Run inside the original GitHub repository, or use the self-contained ZIP.' >&2;exit 1; }
python3 "$root/tools/assemble-v2.20.py"
SOURCE="$root/releases/v2.20/ryoiku_lolipop_student_schedule_v2_20_ftp_full.zip" python3 - <<'PY'
from pathlib import Path
import hashlib,os,zipfile
source=Path(os.environ['SOURCE'])
expected='89d3db9fd235f15705ed7cab7e8787df8f8b852d9c009797b991dfc6311dfafe'
if hashlib.sha256(source.read_bytes()).hexdigest()!=expected:
    raise SystemExit('Checksum mismatch. Will not extract')
with zipfile.ZipFile(source) as z:
    chosen=[x for x in z.infolist() if x.filename.startswith('upload_to_domain_root/')]
    for m in chosen:
        # Block absolute paths, traversal, and symlinks.
        target=Path(m.filename)
        if '..' in target.parts or target.is_absolute() or (m.external_attr>>16)&0o170000==0o120000:
            raise SystemExit('Unsafe archive entry')
    for m in chosen:z.extract(m,'.')
assert Path('upload_to_domain_root/_private/app/VERSION').read_text().strip()=='2.20'
print('Extracted verified v2.20 release sources')
PY