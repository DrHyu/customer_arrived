
# Activate enviroment
source ./env/bin/activate

# Start celery workers
# celery worker -A app.celery --loglevel=info --concurrency 10 &
# celery worker -A app.celery --loglevel=INFO --concurrency=10 -n worker1@%h
# celery worker -A app.celery --loglevel=INFO --concurrency=10 -n worker2@%h
# celery worker -A app.celery --loglevel=INFO --concurrency=10 -n worker3@%h
sh start_celery.sh


# Start flask server
python app.py debug &

# Start telegramBot
python telegramBot.py &
