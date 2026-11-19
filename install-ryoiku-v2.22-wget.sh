#!/usr/bin/env bash
# Download and install the public, pinned v2.22 Docker LAN test release.
# No GitHub personal access token is required.
set -Eeuo pipefail

REPO="kamo0715/ryoiku-install"
VERSION="v2.22"
NAME="ryoiku-v2.22-docker-lan-test"
ARCHIVE="${NAME}.zip"
EXPECTED_SHA256="24c3898f5f9a1e38d080e322afdd14ae85df559074b50ada7d31c9a56b556b84"
RELEASE_URL="https://github.com/${REPO}/releases/download/${VERSION}/${ARCHIVE}"
DEST_DIR="${HOME}"
DOWNLOAD_ONLY=false

usage() {
  cat <<'USAGE'
Usage: bash install-ryoiku-v2.22-wget.sh [--download-only] [--dir DIRECTORY]
  --download-only  Download and verify ZIP; do not modify Docker.
  --dir DIRECTORY  Download and extract into DIRECTORY (default: $HOME).
  -h, --help       Show this help.

Uses public GitHub Releases via HTTPS/wget. Does not require a token.
Only verified old Ryoiku application containers are removed on install.
Docker volumes and all other containers are retained.
USAGE
}

while (($#)); do
  case "$1" in
    --download-only) DOWNLOAD_ONLY=true; shift ;;
    --dir)
      (($# >= 2)) || { echo 'Missing directory for --dir' >&2; exit 2; }
      DEST_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if (( EUID == 0 )) && [[ "$DOWNLOAD_ONLY" == false ]]; then
  echo 'Run this script as your Ubuntu user; it uses sudo only for Docker when needed.' >&2
  exit 2
fi

for cmd in wget sha256sum unzip mktemp; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "Missing command: $cmd" >&2; exit 1;
  }
done

mkdir -p -- "$DEST_DIR"
DEST_DIR="$(cd -- "$DEST_DIR" && pwd -P)"
DEST_ZIP="$DEST_DIR/$ARCHIVE"

verify_zip() {
  local path="$1"
  [[ -s "$path" ]] || return 1
  printf '%s  %s\n' "$EXPECTED_SHA256" "$path" | sha256sum --status -c - || return 1
  unzip -tq "$path" >/dev/null || return 1
}

if verify_zip "$DEST_ZIP"; then
  echo "Verified existing release ZIP: $DEST_ZIP"
else
  tmp="$(mktemp -d)"
  trap 'rm -rf -- "${tmp:-}"' EXIT
  echo "Downloading ${VERSION} from public GitHub Releases (no token)..."
  # wget's --output-document may leave an empty file on HTTP errors.
  wget --https-only --max-redirect=10 --tries=3 --timeout=45 \
    --output-document="$tmp/$ARCHIVE" "$RELEASE_URL"
  if ! verify_zip "$tmp/$ARCHIVE"; then
    echo 'ERROR: downloaded file failed the pinned SHA-256 or ZIP integrity check.' >&2
    exit 1
  fi
  mv -f -- "$tmp/$ARCHIVE" "$DEST_ZIP"
  echo "Verified SHA-256: $EXPECTED_SHA256"
fi

echo "Downloaded: $DEST_ZIP"
if [[ "$DOWNLOAD_ONLY" == true ]]; then
  echo 'Download-only mode; no Docker containers or files were changed.'
  exit 0
fi

[[ "$(uname -s)" == Linux ]] || { echo 'Docker installer requires Linux.' >&2; exit 1; }
[[ "$(uname -m)" == x86_64 ]] || { echo 'Docker installer requires x86_64/AMD64.' >&2; exit 1; }

if [[ -e "$DEST_DIR/$NAME" && ! -f "$DEST_DIR/$NAME/compose.yaml" ]]; then
  echo "ERROR: $DEST_DIR/$NAME exists but is not a known Ryoiku Docker directory." >&2
  exit 1
fi

echo "Extracting the verified ${VERSION} ZIP..."
unzip -oq "$DEST_ZIP" -d "$DEST_DIR"
APP_DIR="$DEST_DIR/$NAME"
[[ -f "$APP_DIR/install-lan-test.sh" && -f "$APP_DIR/remove-old-ryoiku.sh" ]] || {
  echo 'ERROR: expected Docker installation scripts were not found.' >&2; exit 1;
}

# If v2.22 is new, reuse LAN settings from v2.21 or v2.20 without overwriting.
if [[ ! -e "$APP_DIR/.env" ]]; then
  for OLD_ENV in "$DEST_DIR/ryoiku-v2.21-docker-lan-test/.env" "$DEST_DIR/ryoiku-v2.20-docker-lan-test/.env"; do
    if [[ -f "$OLD_ENV" ]]; then
      cp -- "$OLD_ENV" "$APP_DIR/.env"
      chmod 600 "$APP_DIR/.env"
      echo "Reusing previous LAN settings: $OLD_ENV"
      break
    fi
  done
fi

chmod +x "$APP_DIR/install-lan-test.sh" "$APP_DIR/remove-old-ryoiku.sh"
cd -- "$APP_DIR"
echo 'Checking recognized old Ryoiku containers (no changes yet)...'
if docker info >/dev/null 2>&1; then
  ./remove-old-ryoiku.sh --check
  ./install-lan-test.sh
else
  command -v sudo >/dev/null 2>&1 || { echo 'sudo is required for Docker access.' >&2; exit 1; }
  sudo ./remove-old-ryoiku.sh --check
  sudo ./install-lan-test.sh
fi

echo
echo "Installed ${VERSION} in: $APP_DIR"
echo 'Get the initial admin code (if first setup is not yet completed):'
echo "  cd \"$APP_DIR\" && sudo docker compose exec -T ryoiku cat /data/INITIAL_ADMIN_CODE.txt"
echo 'Test with fictional data only. HTTP traffic is not encrypted.'