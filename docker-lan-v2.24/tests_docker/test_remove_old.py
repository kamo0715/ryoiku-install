#!/usr/bin/env python3
"""No-Docker unit checks for the guarded legacy Ryoiku container cleanup helper."""
import os
import subprocess
import tempfile
from pathlib import Path

SCRIPT=Path(__file__).resolve().parent.parent/'remove-old-ryoiku.sh'
FAKE_DOCKER = '''#!/bin/sh
set -eu
case "$1" in
  info) exit 0 ;;
  ps) if [ "${MOCK_PRESENT:-}" = 1 ]; then echo '1234abc'; fi; exit 0 ;;
  inspect)
    case "$3" in
      *Config.Image*) printf '%s\\n' "${MOCK_IMAGE:-example/ryoiku-old:v2.8}" ;;
      *compose.service*) printf '%s\\n' "${MOCK_SERVICE:-ryoiku}" ;;
      *compose.project*) printf '%s\\n' "${MOCK_PROJECT:-ryoiku}" ;;
    esac
    exit 0 ;;
  rm) printf '%s\\n' "$4" >> "${MOCK_LOG:?}"; exit 0 ;;
esac
exit 23
'''

def run(mode, image='example/ryoiku-old:v2.8', present='1'):
    with tempfile.TemporaryDirectory() as td:
        d=Path(td)
        fake=d/'docker'
        fake.write_text(FAKE_DOCKER, encoding='utf-8')
        fake.chmod(0o755)
        log=d/'removed.txt'
        env={**os.environ,'PATH':str(d)+os.pathsep+os.environ.get('PATH',''),
             'MOCK_IMAGE':image,'MOCK_PRESENT':present,'MOCK_LOG':str(log),
             'MOCK_SERVICE':'nginx' if image.startswith('unrelated/') else 'ryoiku',
             'MOCK_PROJECT':'unrelated' if image.startswith('unrelated/') else 'ryoiku'}
        proc=subprocess.run(['bash',str(SCRIPT),mode],capture_output=True,text=True,env=env)
        return proc,log.read_text().splitlines() if log.exists() else []

check, removed=run('--check')
assert check.returncode==0,(check.stdout,check.stderr)
assert removed==[]
execute, removed=run('--remove')
assert execute.returncode==0,(execute.stdout,execute.stderr)
assert set(removed)=={'minecraft-ryoiku-web','ryoiku-lan-test','ryoiku-curriculum','ryoiku-web'},removed
reject, removed=run('--remove',image='unrelated/nginx:latest')
assert reject.returncode!=0 and removed==[],(reject.stdout,reject.stderr,removed)
empty, removed=run('--remove',present='0')
assert empty.returncode==0 and removed==[],(empty.stdout,empty.stderr)
print('OK: recognized app only; unrelated containers are rejected; no deletion in check mode')
