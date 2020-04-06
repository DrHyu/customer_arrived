''' customer arrived flask app '''
import sys
import re
import logging
import time
import json
import zmq


from celery import Celery, signals
from celery.utils.log import get_task_logger
from flask_celery import make_celery

from flask import Flask, render_template, request, Response, url_for, jsonify
from datetime import datetime


logging.basicConfig(format='%(asctime)s %(levelname)s %(lineno)d:%(filename)s\
                    (%(process)d) - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)
celery_logger = get_task_logger(__name__)

app = Flask(__name__)

app.config.update(
    CELERY_BROKER_URL='redis://127.0.0.1:6379/0',
    CELERY_RESULT_BACKEND='redis://127.0.0.1:6379/0'
)

# Initialize Celery
celery = make_celery(app)

ZMQ_TX_PORT = "tcp://127.0.0.1:5678"
ZMQ_BC_PORT = "tcp://127.0.0.1:5680"


@app.route('/', methods=['GET', 'POST'])
def index():
    ''' homepage '''
    return render_template('index.html', order_id=request.args.get('order_id'))


# @app.route('/submit_form/<int:purchase_code>,<int:parking_slot>', methods=['GET,POST'])
@app.route('/submit_form', methods=['GET', 'POST'])
def submit_form():
    ''' user submited data '''

    try:
        if request.method == 'POST':
            purchase_code = int(request.form.get('purchase_code'))
            parking_slot = request.form.get('parking_slot')
        elif request.method == 'GET':
            purchase_code = int(request.args.get('purchase_code'))
            parking_slot = request.args.get('parking_slot')
        else:
            return render_template('submited.html', failed="Parametres incorrectes")

        match = re.match(r'option(\d)', parking_slot)
        if not match:
            return render_template('submited.html', failed="Parametres incorrectes")
        else:
            parking_slot = match.group(1)
    except:
        return render_template('submited.html', failed="Parametres incorrectes")

    # ZeroMQ Context
    context = zmq.Context()

    # Define the socket using the "Context"
    sock = context.socket(zmq.REQ)
    sock.connect(ZMQ_TX_PORT)

    # Poller to recieve response with a timeout
    rx_poller = zmq.Poller()
    rx_poller.register(sock, zmq.POLLIN)

    # Send data to telegram bot
    req_data = {'order_id': purchase_code, 'parking_slot': parking_slot}
    sock.send_json(req_data)

    events = dict(rx_poller.poll(2000))  # 2 sec timeout

    if not events:
        # No response was received
        return render_template('submited.html', failed="No es posible conectar amb el servidor de telegram", order_id=purchase_code)

    response = sock.recv_json()

    if 'status' not in response or response['status'] is not True:
        logger.error('Status was not ok => {}'.format(response))
        return render_template('submited.html', failed="No es posible conectar amb el servidor de telegram", order_id=purchase_code)
    else:
        return render_template('submited.html', order_id=purchase_code)


###########################################################
# CELERY STUFF
###########################################################


@app.route('/get_order_status/<int:order_id>', methods=['POST'])
def get_order_status(order_id):
    logger.info('req to get order status for {}'.format(order_id))
    task = fetch_order_update.delay(order_id)
    return jsonify({}), 202, {'Location': url_for('taskstatus', task_id=task.id)}


@celery.task(bind=True, name='app.fetch_order_update')
def fetch_order_update(self, order_id):
    ''' wait for an order status update '''

    context = zmq.Context()
    sock = context.socket(zmq.SUB)

    # Define subscription and messages with prefix to accept.
    sock.setsockopt(zmq.SUBSCRIBE, b'')
    sock.connect(ZMQ_BC_PORT)

    old_status = None
    txt = ""

    while True:
        while True:
            # wait untill there is an update for our order_id
            json_data = json.loads(sock.recv())
            # celery_logger.info('ID {} looking for {} -> fetched {}'.format(order_id, json_data, self.request.id))
            if 'order_id' in json_data \
                    and 'status' in json_data\
                    and json_data['order_id'] == order_id:
                break
            else:
                # self.update_state(state='PENDING', meta={})
                pass

        status = json_data['status']
        logger.info('order {}: old_status {} => new_status {}'.format(order_id, old_status, status))
        if old_status != status:
            logger.info('order {}: old_status {} => new_status {}'.format(order_id, old_status, status))
            old_status = status
            txt = ""
            if status is None:
                txt = "error"
            elif status == 0:
                txt = "Procesant"
            elif status == 1:
                txt = "Missatge enviat a la farmacia"
            elif status == 2:
                txt = "Preparant comanda"
                break
            elif status == 3:
                txt = "Comanda en espera"
            elif status == 4:
                txt = "Comanda cancelada"
                break

            logger.info('order {}: old_status {} => new_status {}'.format(order_id, old_status, status))
            self.update_state(state='PROGRESS', meta={'txt': txt})

    logger.info('Finshed status update with txt {}'.format(txt))
    # Unsubscribe from socket
    sock.disconnect(ZMQ_BC_PORT)
    # Will get here after an order has been transitioned to ready or canceled or timeout
    return {'txt': txt}


@app.route('/status/<task_id>')
def taskstatus(task_id):
    task = fetch_order_update.AsyncResult(task_id)

    logger.info('task status {}'.format(task.state ))
    if task.state == 'PENDING':
        response = {
            'txt': "Processant...",
            'state': task.state
        }
    elif task.state != 'FAILURE':
        response = {
            'txt': task.info.get('txt', "ERROR 1"),
            'state': task.state
        }
    else:
        response = {
            'txt': "ERROR",
            'state': task.state
        }
        logger.error('FALIURE STATE !'.format())

    return jsonify(response)


if __name__ == '__main__':
    
    debug = False
    if 'debug' in sys.args:
        debug = True
    if 'windows' in sys.args:
        app.run(debug=debug)
    else:
        app.run(host='0.0.0.0', debug=debug)
    
