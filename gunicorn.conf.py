import os
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
worker_class = "gthread"
workers = 2
threads = 4
timeout = 120
loglevel = "info"
accesslog = "-"
errorlog = "-"
