#!/bin/sh
# Secret-leak check (spec section 12, M7): search every container's logs and a full
# database dump for plaintext secrets. Exits 1 if any secret is found.
#
#   scripts/secret-leak-check.sh [-p compose-project] SECRET [SECRET ...]
#
# Pass the real tokens, PATs and passwords you entered (or the e2e test's canaries).
# Uses "docker compose"; set COMPOSE="podman compose" for Podman.
set -eu

COMPOSE=${COMPOSE:-docker compose}
PROJECT_ARGS=""
if [ "${1:-}" = "-p" ]; then
  PROJECT_ARGS="-p $2"
  shift 2
fi
if [ "$#" -eq 0 ]; then
  echo "usage: $0 [-p compose-project] SECRET [SECRET ...]" >&2
  exit 2
fi

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT

# shellcheck disable=SC2086
$COMPOSE $PROJECT_ARGS logs --no-color > "$workdir/logs.txt" 2>&1
# shellcheck disable=SC2086
$COMPOSE $PROJECT_ARGS exec -T db pg_dump -U tt -d tickettrail > "$workdir/dump.sql"

echo "Scanned $(wc -l < "$workdir/logs.txt") log lines and $(wc -l < "$workdir/dump.sql") dump lines."
found=0
for secret in "$@"; do
  for source in logs.txt dump.sql; do
    if grep -qF -- "$secret" "$workdir/$source"; then
      echo "LEAK: a secret (${#secret} characters) was found in $source" >&2
      found=1
    fi
  done
done
if [ "$found" -eq 0 ]; then
  echo "No plaintext secret found."
fi
exit "$found"
