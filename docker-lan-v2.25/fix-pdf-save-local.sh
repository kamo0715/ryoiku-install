#!/usr/bin/env bash
# Safe in-place v2.20 PDF import-save hotfix. No data or volumes are removed.
set -Eeuo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
file='upload_to_domain_root/_private/app/templates/support_form.html'
[[ -f "$file" && ! -L "$file" ]] || { echo "File missing or unsafe: $file" >&2; exit 1; }
python3 - "$file" <<'PY'
from pathlib import Path
import sys,shutil
p=Path(sys.argv[1]); old='<form class="panel stack" method="post">'
new='<form class="panel stack" method="post" action="/children/{{child.id}}/support/new">'
s=p.read_text(encoding='utf-8')
if s.count(new)==1 and old not in s:
 print('PDF save destination is already fixed')
elif s.count(old)==1 and new not in s:
 backup=p.with_suffix(p.suffix+'.before-savefix.bak')
 if not backup.exists():shutil.copy2(p,backup)
 p.write_text(s.replace(old,new),encoding='utf-8')
 print(f'Fixed save destination; backup: {backup}')
else:
 raise SystemExit('Unknown template version; left unchanged. Confirm the original application version.')
PY
if ! command -v docker >/dev/null; then echo 'Docker not installed' >&2; exit 1; fi
echo 'Rebuilding only this compose app; named volumes are preserved...'
docker compose up -d --build --no-deps ryoiku
printf '\nDone. Open the PDF import form again and retry.\n'
