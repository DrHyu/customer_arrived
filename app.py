import re

from flask import Flask, render_template, request
from telegramBot import TelegramBot, CHAT_ID, API_KEY

global telegram_bot
telegram_bot = TelegramBot(api_key=API_KEY, chat_with=CHAT_ID)

app = Flask(__name__)


@app.route('/', methods=['GET', 'POST'])
def index():
    print("fkdsjaf;lkasjdf;lkajsd;flkajs;lk")
    print(request.args.get('order_id'))
    return render_template('index.html', order_id=request.args.get('order_id'))


# @app.route('/submit_form/<int:purchase_code>,<int:parking_slot>', methods=['GET,POST'])
@app.route('/submit_form', methods=['GET', 'POST'])
def submit_form():

    # POST: Sign user in
    if request.method == 'POST':
        # Get Form Fields
        purchase_code = request.form.get('purchase_code')
        parking_slot = request.form.get('parking_slot')

        match = re.match("option(\d)", parking_slot)
        if not match:
            return "Not correct"
        else:
            parking_slot = match.group(1)

        telegram_bot.add_new_order(int(purchase_code), int(parking_slot))
        return (" {} {} ".format(purchase_code, parking_slot))

    elif request.method == 'GET':
        purchase_code = request.args.get('purchase_code')
        parking_slot = request.args.get('parking_slot')

        match = re.match("option(\d)", parking_slot)
        if not match:
            return "Not correct"
        else:
            parking_slot = match.group(1)

        telegram_bot.add_new_order(int(purchase_code), int(parking_slot))
        return (" {} {} ".format(purchase_code, parking_slot))
    else:
        return "Could not get parameters !"


if __name__ == '__main__':

    try:
        app.run(debug=True, use_reloader=False)
    finally:
        telegram_bot.stop()

    # app.run(debug=True)
