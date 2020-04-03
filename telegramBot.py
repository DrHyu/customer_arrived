#!/usr/bin/env python
# -*- coding: utf-8 -*-
# This program is dedicated to the public domain under the CC0 license.

"""
Basic example for a bot that uses inline keyboards.
"""
import logging
import time
import re

from threading import Lock, Thread
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler


logging.basicConfig(format='%(asctime)s %(levelname)s %(lineno)d:%(filename)s(%(process)d) - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)


CHAT_ID = 968017190
API_KEY = "1173915016:AAFa-G9Jo-gBzGXSIU38EIqUGDcVus1kZhQ"


class Order():

    ORDER_REMINDER_TIMEOUT = 5
    ORDER_POSPONED_DURATION = 120
    ORDER_MAX_DURATION = 600

    def __init__(self, order_id, parking_slot):

        self.order_id = order_id
        self.parking_slot = parking_slot
        self.date_created = time.time()
        self.last_reminder_time = None
        self.pospone_until = None

        self.message = None

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        return 'Comanda {} @ parking {}'.format(self.order_id, self.parking_slot)


class TelegramBot():

    ORDER_ACCEPTED = 0
    ORDER_DELAYED = 1
    ORDER_CANCELED = 2

    KEYBOARD = [[InlineKeyboardButton("ARA VAIG", callback_data=ORDER_ACCEPTED),
                 InlineKeyboardButton("OCUPAT", callback_data=ORDER_DELAYED),
                 InlineKeyboardButton("CANCELAR", callback_data=ORDER_CANCELED)], ]

    def __init__(self, api_key=None, chat_with=CHAT_ID):

        logger.info(
            'NEW TELEGRAM BOT ISNTANCE ----------------------------------------------'.format())

        logger.fatal('{}'.format(__name__))

        self.chat_with = chat_with

        self.pending_orders_lock = Lock()
        self.pending_orders = []

        self._thread = None
        self._end_lock = Lock()

        self._bot = None
        self._updater = None

        self._api_key = api_key
        self.start()

    def start(self):

        if not self._end_lock.acquire(blocking=False) or self._thread != None:
            logger.fatal('Thread already runing'.format())
            return

        self._bot = Bot(self._api_key)
        self._updater = Updater(self._api_key, use_context=True)

        self._updater.dispatcher.add_handler(
            CallbackQueryHandler(self.custom_keyboard_answer))

        self._updater.dispatcher.add_handler(
            CommandHandler('start', self.welcome))
        self._updater.dispatcher.add_handler(CommandHandler('help', self.help))
        self._updater.dispatcher.add_error_handler(self.error)

        # Launch updater thread
        self._updater.start_polling()

        self._thread = Thread(target=self._run)
        self._thread.daemon = True
        self._thread.start()

    def _run(self):
        while True:
            self.send_pending_messages()
            time.sleep(1)
            # Exit condition
            if self._end_lock.acquire(blocking=False):
                break

    def stop(self):
        if not self._end_lock.locked() or self._thread is None:
            logger.fatal('Thread already finished'.format())
        else:
            self._end_lock.release()
            self._updater.stop()
            self._thread = None
            time.sleep(1)

    def runing(self):
        return self._end_lock.locked()

    def add_new_order(self, order_id, parking_slot):
        with self.pending_orders_lock:
            self.pending_orders.append(Order(order_id, parking_slot))

    def custom_keyboard_answer(self, update, context):
        query = update.callback_query
        # print(query)
        query.answer()

        match = re.search("Comanda (\w+)",
                          query.message.text)
        found_order_id = None
        if match:
            found_order_id = int(match.group(1))
        else:
            logger.error('Incorrect format of received message: {}'.format(
                query.message.text))
            query.edit_message_text("--")
            return

        with self.pending_orders_lock:

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
                o.order_id, o.parking_slot)

            if int(query.data) == TelegramBot.ORDER_ACCEPTED:
                self.pending_orders.remove(order)
                response += "COMPLETADA"
            elif int(query.data) == TelegramBot.ORDER_DELAYED:
                order.pospone_until = time.time() + Order.ORDER_POSPONED_DURATION
                response += "POSPOSADA (2mins)"
            elif int(query.data) == TelegramBot.ORDER_CANCELED:
                self.pending_orders.remove(order)
                response += "CANCELADA"

            query.edit_message_text(text=response)

    def send_pending_messages(self):

        with self.pending_orders_lock:
            new_messages_sent = 0
            old_messages_updated = 0

            reply_markup = InlineKeyboardMarkup(TelegramBot.KEYBOARD)
            for o in self.pending_orders:

                # First message
                if o.message is None:
                    logger.debug(
                        'Sending initial message for id {}'.format(o.order_id))
                    reply_markup = InlineKeyboardMarkup(TelegramBot.KEYBOARD)
                    o.message = self._bot.sendMessage(
                        chat_id=self.chat_with, text=str(o), reply_markup=reply_markup)
                    o.last_reminder_time = time.time()

                    new_messages_sent += 1

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

            # Send a dummy message and delete to trigger a user alter
            if new_messages_sent == 0 and old_messages_updated > 0:
                msg = self._bot.sendMessage(
                    chat_id=self.chat_with, text="Update.")
                self._bot.deleteMessage(
                    chat_id=msg.chat_id, message_id=msg.message_id)

    def help(self, update, context):
        update.message.reply_text("Use /start to test this bot.")

    def error(self, update, context):
        """Log Errors caused by Updates."""
        logger.warning('Update "%s" caused error "%s"', update, context.error)

    def welcome(self, update, context):
        update.message.reply_text('Welcome !')


telegram_bot = TelegramBot(api_key=API_KEY, chat_with=CHAT_ID)

if __name__ == '__main__':
    # telegram_bot = TelegramBot(api_key=API_KEY, chat_with=CHAT_ID)

    try:
        telegram_bot.add_new_order(2222, 2)
        telegram_bot.add_new_order(1111, 1)

        start_time = time.time()
        while time.time() - start_time < 30:
            print("Runing ---" + str(time.time() - start_time))
            telegram_bot.send_pending_messages()
            time.sleep(2)
    finally:
        telegram_bot.stop()

    exit()
