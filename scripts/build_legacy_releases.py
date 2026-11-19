#!/usr/bin/env python3
"""Validate and package historical self-contained Linux shell installers. No --apply ever run."""
from pathlib import Path
import argparse, base64, hashlib, io, re, subprocess, zipfile

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(r"(?m)^\s*base64\s+(?:--decode|-d)\b[^\n]*<<\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")


def b64_archive(content: str) -> bytes | None:
    m = PATTERN.search(content)
    if not m:
        return None
    delimiter = m.group(1)
    start = content.index('\n', m.end()) + 1
    stop = re.search(r'(?m)^\s*' + re.escape(delimiter) + r'\s*$', content[start:])
    if not stop:
        raise RuntimeError('embedded payload delimiter not found')
    chars = ''.join(content[start:start + stop.start()].split())
    out = base64.b64decode(chars, validate=True)
    with zipfile.ZipFile(io.BytesIO(out)) as archive:
        assert archive.testzip() is None
    return out


def build(path: Path, output_root: Path):
    m = re.search(r'v(\d+\.\d+)', path.name)
    if not m:
        raise RuntimeError(path)
    version = 'v' + m.group(1)
    out = output_root / version
    out.mkdir(parents=True,exist_ok=True)
    subprocess.run(['bash', '-n', str(path)], check=True)
    raw = path.read_bytes()
    archive = b64_archive(raw.decode('utf-8'))
    (out / path.name).write_bytes(raw)
    embedded_name = None
    if archive is not None:
        sha = hashlib.sha256(archive).hexdigest()
        # scripts v2.2-2.7 contain SHA pinning for safe offline verification
        match = re.search(r'EXPECTED_(?:PATCH_)?SHA256=["\']([0-9a-f]{64})["\']', raw.decode())
        if match and match.group(1) != sha:
            raise RuntimeError(f'Bad pinned archive SHA for {path.name}: {sha}')
        embedded_name = f'ryoiku_{version.replace(".","_")}_embedded_payload.zip'
        (out / embedded_name).write_bytes(archive)
    elif version == 'v2.8':
        with zipfile.ZipFile(out / 'ryoiku_v2_8_source_files.zip', 'w', zipfile.ZIP_DEFLATED) as z:
            for item in ('support_analyzer.py','apply_patch.py'):
                p=ROOT/'v2.8'/item
                if not p.exists():
                    raise RuntimeError('missing pinned v2.8 file: '+item)
                z.write(p,arcname=item)
    else:
        raise RuntimeError('Expected an embedded update ZIP: '+path.name)
    with zipfile.ZipFile(out / f'ryoiku_{version.replace(".","_")}_scripts_bundle.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.iterdir()):
            if p.is_file() and not p.name.endswith('_scripts_bundle.zip'):
                z.write(p,arcname=p.name)
    (out/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(out.iterdir()) if p.is_file() and p.name!='SHA256SUMS.txt'), encoding='utf-8')
    (out/'RELEASE_NOTES.md').write_text(
        f'### 療育カリキュラム管理 {version} — 旧Linux/Docker版\n\n'
        '既存の `.sh` を `bash -n` で構文検証し、配布用にまとめました。'
        + (' 内蔵ZIPを抽出して整合性を確認した配布物も同梱しています。' if embedded_name else ' v2.8は固定コミット参照型のため、参照先のソースファイルを同梱しています。')
        + '\n\n**注意:** 旧Docker環境向けであり、現行ロリポップFTP版への適用はできません。'
        '実機に対する `--apply` は実行していません。既存バージョン・バックアップ・スクリプトの `--help` を確認してください。\n',encoding='utf-8')
    print('Prepared '+version+' '+path.name+' archive '+str(len(archive) if archive else 'reference'))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,default=Path('dist/legacy'));args=ap.parse_args()
    scripts=sorted(ROOT.glob('install-ryoiku-v*.sh'))+sorted(ROOT.glob('update-ryoiku-v*.sh'))
    if not scripts: raise RuntimeError('No historical installers found')
    for script in scripts:build(script,args.out)
    patch=ROOT/'release-sources'/'ryoiku-v2.9-litalico-mapping-patch.zip'
    if patch.exists():
        dest=args.out/'v2.9';dest.mkdir(parents=True,exist_ok=True)
        (dest/patch.name).write_bytes(patch.read_bytes())
        (dest/'SHA256SUMS.txt').write_text(hashlib.sha256(patch.read_bytes()).hexdigest()+'  '+patch.name+'\n')
        (dest/'RELEASE_NOTES.md').write_text('### v2.9 — LITALICOマッピング修正パッチ\n\n保存済み差分ZIPのみです。**完全版ではありません。**適用元の版を確認してください。\n',encoding='utf-8')

if __name__=='__main__':main()