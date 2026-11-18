#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 manage.py init-db
python3 manage.py check
exec python3 server.py
