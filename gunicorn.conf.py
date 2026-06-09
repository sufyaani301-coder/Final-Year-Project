import os
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
worker_class = "eventlet"
workers = 1
timeout = 120
loglevel = "debug"
# Force gunicorn logs to stdout so Railway captures them in deploy logs.
accesslog = "-"
errorlog = "-"
