
# Activate enviroment
source ./env/bin/activate

# Start celery workers
celery worker -A app.celery --loglevel=info --concurrency 10 &

# Start flask server
python app.py debug &

# Start telegramBot
python telegramBot.py &
