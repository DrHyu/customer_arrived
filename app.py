''' customer arrived flask app '''
import re
import logging
import time
import json
import zmq

from flask import Flask, render_template, request, Response
from datetime import datetime


logging.basicConfig(format='%(asctime)s %(levelname)s %(lineno)d:%(filename)s\
                    (%(process)d) - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)

app = Flask(__name__)

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


def wait_for_order_status_update(order_id):
    ''' get order status from DB'''

    result = None
    if result:
        return result.status
    else:
        return None


@app.route('/order_status/<int:order_id>')
def stream(order_id):
    def eventStream():

        # Create a new socket to listen to the order status updates
        context = zmq.Context()
        sock = context.socket(zmq.SUB)

        # Define subscription and messages with prefix to accept.
        sock.setsockopt(zmq.SUBSCRIBE, b'')
        sock.connect(ZMQ_BC_PORT)

        while True:
            # status = wait_for_order_status_update(order_id)
            json_data = None
            while True:
                # wait untill there is an update for our order_id
                json_data = json.loads(sock.recv())
                if 'order_id' in json_data \
                        and 'new_status' in json_data\
                        and json_data['order_id'] == order_id:
                    break

            status = json_data['new_status']
            logger.info("Received order {} status update {}".format(order_id, status))

            txt = ""
            if status is None:
                txt = "error"
            elif status == 0:
                txt = "Procesant"
            elif status == 1:
                txt = "Enviat"
            elif status == 2:
                txt = "Preparant comanda"
            elif status == 3:
                txt = "Comanda en espera"
            elif status == 4:
                txt = "Comanda cancelada"

            yield 'data: {}\n\n'.format(txt)
            time.sleep(1)

    return Response(eventStream(), mimetype="text/event-stream")


if __name__ == '__main__':
    app.run(host='0.0.0.0')
