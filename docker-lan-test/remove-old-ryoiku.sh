#!/usr/bin/env bash
# Remove only positively identified older Ryoiku application containers.
# Named volumes, images, settings and other services are intentionally retained.
set -Eeuo pipefail

usage() {
  cat <<'USAGE'
Usage: ./remove-old-ryoiku.sh --check | --remove
  --check    Show recognized old Ryoiku containers; no modifications (default)
  --remove   Stop and remove recognized Ryoiku app containers only

Recognized container names: minecraft-ryoiku-web, ryoiku-lan-test,
ryoiku-curriculum, ryoiku-web. A known name alone is NOT sufficient:
the Docker image or Compose service must also indicate the Ryoiku app.
Other containers, named volumes and Docker images are never removed.
USAGE
}

mode="${1:---check}"
case "$mode" in
  --check|--remove) ;;
  -h|--help) usage; exit 0;;
  *) usage >&2; exit 2;;
esac
command -v docker >/dev/null || { echo 'Error: docker command not found' >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo 'Error: Docker daemon unavailable or insufficient permissions' >&2; exit 1; }

known_names=(minecraft-ryoiku-web ryoiku-lan-test ryoiku-curriculum ryoiku-web)
found=0
declare -a confirmed=()
for name in "${known_names[@]}"; do
  # Exact full name only; never match other containers by substring.
  ids="$(docker ps -aq --filter "name=^/${name}$")"
  [[ -n "$ids" ]] || continue
  # Name isn't trusted: inspect positive app markers before any destructive operation.
  image="$(docker inspect --format '{{.Config.Image}}' "$name")"
  service="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$name")"
  project="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$name")"
  recognized=false
  case "$image" in
    *ryoiku*|*Ryoiku*) recognized=true;;
  esac
  if [[ "$service" == ryoiku ]] && [[ "$project" == *ryoiku* ]]; then
    recognized=true
  fi
  if [[ "$recognized" != true ]]; then
    printf 'STOP: "%s" exists but does not have recognizable Ryoiku image/Compose identity. No changes made.\n' "$name" >&2
    exit 1
  fi
  printf '%s: container=%s, image=%s, compose_service=%s, compose_project=%s\n' \
    "${mode#--}" "$name" "$image" "$service" "$project"
  confirmed+=("$name")
  found=$((found+1))
done
# Validate EVERY candidate before removing ANY container; reject partial cleanup.
if [[ "$mode" == --remove ]]; then
  for name in "${confirmed[@]}"; do
    # Explicitly NEVER pass -v: named/anonymous volumes are preserved.
    docker rm -f -- "$name" >/dev/null
    printf 'Removed Ryoiku container: %s (Docker volumes kept)\n' "$name"
  done
fi
if [[ "$found" == 0 ]]; then
  echo 'No recognized old Ryoiku container found. No other container was changed.'
fi