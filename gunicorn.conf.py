"""Production server settings (Render / any Linux host).

ONE worker on purpose: background jobs and their progress live in that worker's memory,
so a second worker could not answer /job/<id>/status for a job the first one started.
Threads give concurrency for page loads and status polling while a job runs."""
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '7860')}"
workers = 1
threads = int(os.environ.get("GUNICORN_THREADS", "4"))
timeout = 120               # uploads on slow links; scoring itself runs in a background thread
graceful_timeout = 30
preload_app = False         # the demo-precompute thread must start inside the worker, not the master
accesslog = "-"
errorlog = "-"
loglevel = "info"
