/home/jaume/customer_arrived/env/bin/celery multi stopwait cel_worker1@%h cel_worker2@%h cel_worker3@%h -A app.celery --pidfile='/home/jaume/customer_arrived/celery_logs/%N.pid'
# /home/jaume/customer_arrived/env/bin/celery multi restart cel_worker1@%h cel_worker2@%h cel_worker3@%h -A app.celery --pidfile='/home/jaume/customer_arrived/celery_logs/%N.pid'