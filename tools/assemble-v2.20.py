#!/usr/bin/env python3
"""Reassemble the v2.20 full deployment ZIP from tracked Git binary parts.

Requires Python 3.9+; no extra packages or credentials.
"""
from pathlib import Path
from hashlib import sha256
import zipfile
import sys

ROOT = Path(__file__).resolve().parent.parent
PARTS = ROOT / "releases" / "v2.20" / "complete_zip_parts"
OUTPUT = ROOT / "releases" / "v2.20" / "ryoiku_lolipop_student_schedule_v2_20_ftp_full.zip"
EXPECTED_SIZE = 22580402
EXPECTED_SHA256 = "89d3db9fd235f15705ed7cab7e8787df8f8b852d9c009797b991dfc6311dfafe"


def verify(file: Path) -> bool:
    if not file.is_file() or file.stat().st_size != EXPECTED_SIZE:
        return False
    digest = sha256()
    with file.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest() == EXPECTED_SHA256


def main() -> int:
    expected = [PARTS / f"part_{i:03d}.bin" for i in range(30)]
    missing = [str(p) for p in expected if not p.is_file()]
    if missing:
        print(f"ERROR: missing {len(missing)} ZIP parts: {missing[:3]}", file=sys.stderr)
        return 2
    if OUTPUT.exists():
        if verify(OUTPUT):
            print(f"Already verified: {OUTPUT}")
            return 0
        print(f"ERROR: existing ZIP failed hash check: {OUTPUT}", file=sys.stderr)
        return 2

    partial = OUTPUT.with_suffix(".zip.partial")
    try:
        with partial.open("wb") as out:
            for part in expected:
                with part.open("rb") as stream:
                    while chunk := stream.read(1024 * 1024):
                        out.write(chunk)
        if not verify(partial):
            print("ERROR: size or SHA-256 mismatch; check Git-tracked parts", file=sys.stderr)
            return 2
        with zipfile.ZipFile(partial, "r") as archive:
            bad = archive.testzip()
            if bad:
                print(f"ERROR: ZIP corruption in {bad}", file=sys.stderr)
                return 2
        partial.replace(OUTPUT)
        print(f"OK: {OUTPUT}")
        print(f"SHA256: {EXPECTED_SHA256}")
        return 0
    finally:
        if partial.exists():
            partial.unlink()


if __name__ == "__main__":
    raise SystemExit(main())
