#!/bin/bash
cat > /var/app/staging/Procfile << 'PROC'
web: gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:8000 application:application
PROC
