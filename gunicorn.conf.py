import os
bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
worker_class = "sync"
workers = 1
timeout = 120
loglevel = "debug"
accesslog = "-"
errorlog = "-"
