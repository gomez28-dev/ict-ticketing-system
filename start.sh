#!/usr/bin/env bash
set -o errexit

python manage.py migrate --noinput
python manage.py bootstrap_free_staging
python -m gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000}

