"""
wsgi.py — WSGI entry point for production (Gunicorn).

Gunicorn start command (see render.yaml):
  gunicorn wsgi:application --workers 1 --threads 4 --timeout 120
"""

from server import create_app

application = create_app()
