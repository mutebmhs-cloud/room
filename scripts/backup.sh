#!/usr/bin/env sh
set -eu
mkdir -p backups
filename="backups/writer_$(date -u +%Y%m%d_%H%M%S).dump"
docker compose exec -T db pg_dump -U writer -d writer -Fc > "$filename"
chmod 600 "$filename"
printf 'Database backup: %s\n' "$filename"
