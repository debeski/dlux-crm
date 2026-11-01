#!/bin/sh
# dlux stack schema 4
set -e

until nc -z -v -w30 db 5432; do
  echo "Waiting for database..."
  sleep 1
done

exec "$@"
