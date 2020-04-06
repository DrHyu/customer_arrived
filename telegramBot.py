#!/usr/bin/env python
# -*- coding: utf-8 -*-

''' my telegram bot '''

import logging
import time
import re


from threading import Lock, Thread

import sqlite3
import zmq

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler


logging.basicConfig(format='%(asctime)s %(levelname)s %(lineno)d:%(filename)s(%(process)d) - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)


CHAT_ID = 968017190
API_KEY = "1173915016:AAFa-G9Jo-gBzGXSIU38EIqUGDcVus1kZhQ"

ZMQ_RX_PORT = "tcp://127.0.0.1:5678"
ZMQ_BC_PORT = "tcp://127.0.0.1:5680"


class Order():
    ''' order representation '''
    ORDER_REMINDER_TIMEOUT = 5
    ORDER_POSPONED_DURATION = 120
    ORDER_MAX_DURATION = 600

    ORDER_STATUS_PROCESSING = 0
    ORDER_STATUS_SENT = 1
    ORDER_STATUS_ACCEPTED = 2
    ORDER_STATUS_POSPONED = 3
    ORDER_STATUS_CANCELED = 4

    def __init__(self, order_id, parking_slot):

        self.order_id = order_id
        self.parking_slot = parking_slot
        self.date_created = time.time()
        self.last_reminder_time = None
        self.pospone_until = None

        self.status = None
        self.message = None

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        return 'Comanda {} @ parking {}'.format(self.order_id, self.parking_slot)


class TelegramBot():
    ''' telegram bot '''
    ORDER_ACCEPTED = 0
    ORDER_DELAYED = 1
    ORDER_CANCELED = 2

    KEYBOARD = [[InlineKeyboardButton("ARA VAIG", callback_data=ORDER_ACCEPTED),
                 InlineKeyboardButton("OCUPAT", callback_data=ORDER_DELAYED),
                 InlineKeyboardButton("CANCELAR", callback_data=ORDER_CANCELED)], ]

    def __init__(self, api_key=None, chat_with=CHAT_ID):

        logger.info('Initializing Telegram Bot')

        self.chat_with = chat_with

        self.pending_orders_lock = Lock()
        self.pending_orders = []

        self._thread = None
        self._end_lock = Lock()

        self._bot = None
        self._updater = None

        self._api_key = api_key

        self._bot = Bot(self._api_key)
        self._updater = Updater(self._api_key, use_context=True)

        self._updater.dispatcher.add_handler(
            CallbackQueryHandler(self.user_answer))

        self._updater.dispatcher.add_handler(
            CommandHandler('start', self.welcome))
        self._updater.dispatcher.add_handler(CommandHandler('help', self.help))
        self._updater.dispatcher.add_handler(CommandHandler('subscribe', self.subscribe))
        self._updater.dispatcher.add_error_handler(self.error)

        # ZeroMQ Context
        self._zmq_context = zmq.Context()

        # Define a socket through wich flask will pass the new orders
        self._zmq_rx_sock = self._zmq_context.socket(zmq.REP)
        self._zmq_rx_sock.bind(ZMQ_RX_PORT)
        logger.info(
            'New socket @ {} to receive new orders.'.format(ZMQ_RX_PORT))

        # Define a broadcast port where the updates to orders are published
        self._zmq_bc_sock = self._zmq_context.socket(zmq.PUB)
        self._zmq_bc_sock.bind(ZMQ_BC_PORT)
        logger.info(
            'New socket @ {} to broadcast orders status.'.format(ZMQ_BC_PORT))

        logger.info('Init finished succesfully.')

        self.start()

    def start(self):

        if not self._end_lock.acquire(blocking=False) or self._thread is not None:
            logger.fatal('Thread already runing'.format())
            return

        logger.info('Starting telegram updater...')
        # Launch updater thread
        self._updater.start_polling()

        self._thread = Thread(target=self._run)
        self._thread.daemon = True
        logger.info('Starting bot thread...')
        self._thread.start()

        logger.info('All runing !')

    def _run(self):

        if self.chat_with is not None:
            msg = self._bot.sendMessage(chat_id=self.chat_with, text="Telegram server started")
        
        while True:
            # Send pending messages
            self.send_pending_messages()

            # Check if there is a new message request
            try:
                # Get req data
                req_json = self._zmq_rx_sock.recv_json(flags=zmq.NOBLOCK)

                if 'order_id' in req_json and 'parking_slot' in req_json:
                    # Send response
                    self._zmq_rx_sock.send_json({'status': True})
                    # Add new order
                    self.add_new_order(
                        req_json['order_id'], req_json['parking_slot'])
                else:
                    logger.error('Strange request data {}'.format(req_json))
            # Nothing found
            except zmq.ZMQError as e:
                pass

            time.sleep(1)
            # Exit condition
            if self._end_lock.acquire(blocking=False):
                break

    def stop(self):

        if self.chat_with is not None:
            msg = self._bot.sendMessage(chat_id=self.chat_with, text="Shutting down telegram server")

        if not self._end_lock.locked() or self._thread is None:
            logger.fatal('Thread already finished'.format())
        else:
            self._end_lock.release()

            logger.info(
                'Waiting for telegram updater to finish...'.format())
            self._updater.stop()

            logger.info('Waiting for telegram bot to finish...'.format())
            self._thread.join()

            logger.info('Telegram bot stopped'.format())

    def runing(self):
        return self._end_lock.locked()

    ##################################################
    # Orders management
    ##################################################

    def add_new_order(self, order_id, parking_slot):

        with self.pending_orders_lock:
            order = None
            status = None
            # Ensure order is not already in the list
            existing_order = None
            for p_order in self.pending_orders:
                if p_order.order_id == order_id:
                    existing_order = p_order
                    break

            if existing_order:
                order = existing_order
                status = existing_order.status
                logger.info('Attempted to add already existing order to pending order {}'.format(order_id))
                # TODO
                # Super crappy way to do it
                # Allow time for the browser to launch the clerry worker and the worker to listen to this broadcast
                # Pottentially troublesome since we are hodling the lock during this time also
                time.sleep(0.2)
            else:
                order = Order(order_id, parking_slot)
                status = Order.ORDER_STATUS_PROCESSING
                self.pending_orders.append(order)

            self.upd_and_broadcas_order_status([[order,status]])

    def user_answer(self, update, _):
        query = update.callback_query

        query.answer()

        # Get order ID from the query
        match = re.search(r'Comanda (\w+)', query.message.text)
        found_order_id = None
        if match:
            found_order_id = int(match.group(1))
        else:
            logger.error('Incorrect format of received message: {}'.format(
                query.message.text))
            query.edit_message_text("--")
            return

        with self.pending_orders_lock:

            if query.message.chat.id != self.chat_with:
                # User repplied to a message but he is not the owner anymore
                query.edit_message_text(text=query.message.text + '\n You cannot repply as ownership has been transfered')
                return

            # Find order in pending order list
            order = None
            for o in self.pending_orders:
                if o.order_id == found_order_id:
                    order = o
                    break

            if not order:
                logger.error('Got repply for order id {} but current pending orders are {}'.format(
                    found_order_id, self.pending_orders))
                query.edit_message_text("--")
                return

            response = "Comanda {} @ parking {}: -> ".format(
                order.order_id, order.parking_slot)

            if int(query.data) == TelegramBot.ORDER_ACCEPTED:
                self.upd_and_broadcas_order_status(
                    [[order, Order.ORDER_STATUS_ACCEPTED]])
                self.pending_orders.remove(order)
                order.pospone_until = None
                response += "COMPLETADA"
                query.edit_message_text(text=response)
            elif int(query.data) == TelegramBot.ORDER_DELAYED:
                self.upd_and_broadcas_order_status(
                    [[order, Order.ORDER_STATUS_POSPONED]])
                order.pospone_until = time.time() + Order.ORDER_POSPONED_DURATION
                response += "POSPOSADA (2mins)"
                query.edit_message_text(
                    text=response, reply_markup=InlineKeyboardMarkup(TelegramBot.KEYBOARD))

            elif int(query.data) == TelegramBot.ORDER_CANCELED:
                self.upd_and_broadcas_order_status(
                    [[order, Order.ORDER_STATUS_CANCELED]])
                self.pending_orders.remove(order)
                response += "CANCELADA"
                order.pospone_until = None
                query.edit_message_text(text=response)

    def send_pending_messages(self):

        with self.pending_orders_lock:
            new_messages_sent = 0
            old_messages_updated = 0

            reply_markup = InlineKeyboardMarkup(TelegramBot.KEYBOARD)

            status_to_update = []
            for o in self.pending_orders[:]:

                # First message
                if o.message is None:
                    logger.debug(
                        'Sending initial message for id {}'.format(o.order_id))
                    reply_markup = InlineKeyboardMarkup(TelegramBot.KEYBOARD)
                    o.message = self._bot.sendMessage(
                        chat_id=self.chat_with, text=str(o), reply_markup=reply_markup)
                    o.last_reminder_time = time.time()

                    new_messages_sent += 1
                    status_to_update.append([o, Order.ORDER_STATUS_SENT])

                elif time.time() - o.date_created > Order.ORDER_MAX_DURATION:
                    logger.debug(
                        'Order {} was ignored for more than {}'.format(o.order_id, Order.ORDER_MAX_DURATION))
                    self._bot.edit_message_text(chat_id=self.chat_with,
                                                message_id=o.message.message_id,
                                                text="COMANDA IGNORADA ({} s) ==> Comanda {} @ Parking {}".format(
                                                    int(time.time() -
                                                        o.date_created),
                                                    o.order_id,
                                                    o.parking_slot
                                                ),
                                                )

                    o.last_reminder_time = time.time()
                    o.pospone_until = None
                    old_messages_updated += 1

                    status_to_update.append([o, Order.ORDER_STATUS_CANCELED])
                    self.pending_orders.remove(o)

                # If reminder timeout and not in pospone time
                elif time.time() - o.last_reminder_time > Order.ORDER_REMINDER_TIMEOUT and not o.pospone_until:
                    logger.debug(
                        'Sending reminder message for id {}'.format(o.order_id))

                    self._bot.edit_message_text(chat_id=self.chat_with,
                                                message_id=o.message.message_id,
                                                text="RECORDATORI ({} s) ==> Comanda {} @ Parking {}".format(
                                                    int(time.time() -
                                                        o.date_created),
                                                    o.order_id,
                                                    o.parking_slot
                                                ),
                                                reply_markup=reply_markup
                                                )

                    o.last_reminder_time = time.time()
                    old_messages_updated += 1

                elif o.pospone_until and time.time() - o.pospone_until > Order.ORDER_POSPONED_DURATION:
                    logger.debug(
                        'Pospone has run out for id {}'.format(o.order_id))
                    self._bot.edit_message_text(chat_id=self.chat_with,
                                                message_id=o.message.message_id,
                                                text=str(o),
                                                reply_markup=reply_markup
                                                )

                    o.last_reminder_time = time.time()
                    o.pospone_until = None
                    old_messages_updated += 1

                else:
                    pass

            self.upd_and_broadcas_order_status(status_to_update)
            # Send a dummy message and delete to trigger a user alter
            if new_messages_sent == 0 and old_messages_updated > 0:
                msg = self._bot.sendMessage(
                    chat_id=self.chat_with, text="Update.")
                self._bot.deleteMessage(
                    chat_id=msg.chat_id, message_id=msg.message_id)

    def upd_and_broadcas_order_status(self, new_statuses):

        for (order, new_status) in new_statuses:
            # Send a broadcast message with the new order status
            update = {'order_id': order.order_id,
                      'status': new_status}
            self._zmq_bc_sock.send_json(update)
            logger.info('Updating status {}'.format(update))

            order.status = new_status

    ##################################################

    ##################################################
    # Command handlers 
    ##################################################

    def help(self, update, _):
        update.message.reply_text("Use /start to test this bot.")

    def error(self, update, context):
        """Log Errors caused by Updates."""
        logger.warning('Update "%s" caused error "%s"', update, context.error)

    def welcome(self, update, _):
        update.message.reply_text('Welcome !')

    def subscribe(self, update, context):
        print (update.message)
        new_chat_id = update.message.chat.id
        update.message.reply_text('New chat ID {}'.format(new_chat_id))
        update.message.reply_text('This user will now receive all the updates'.format(new_chat_id))

        with self.pending_orders_lock:

            # Notify the old user that ownership has been transfered
            self._bot.sendMessage(
                        chat_id=self.chat_with, text="Ownership has been trasnfered !")


            if self.pending_orders:
                update.message.reply_text('Transfering pending messages'.format(new_chat_id))

            # Update the chat ID
            self.chat_with = new_chat_id

            # All the message IDs on all the orders need to be updated
            # Send placeholders that will be updated in the next iteration of the main thread
            for o in self.pending_orders:
                logger.info('Sent placeholder message for {}'.format(o.order_id))
                msg = self._bot.sendMessage(
                        chat_id=self.chat_with, text="Placeholder for order {}".format(o.order_id))
                o.message = msg

    ##################################################

telegram_bot = TelegramBot(api_key=API_KEY, chat_with=CHAT_ID)

if __name__ == '__main__':
    try:
        while(True):
            time.sleep(1)
    finally:
        telegram_bot.stop()

    exit()
