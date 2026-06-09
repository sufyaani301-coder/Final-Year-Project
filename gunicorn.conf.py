import os
import sys

print(f"=== gunicorn.conf.py loaded, PORT={os.environ.get('PORT')}, Python={sys.version} ===", flush=True)

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
worker_class = "sync"
workers = 1
timeout = 120
loglevel = "debug"
accesslog = "-"
errorlog = "-"

def on_starting(server):
    print("=== gunicorn: on_starting hook ===", flush=True)

def post_fork(server, worker):
    print(f"=== gunicorn: worker {worker.pid} started ===", flush=True)
