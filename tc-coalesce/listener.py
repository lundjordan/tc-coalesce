import traceback
import sys
import os
import json
import socket
import logging
import redis
import signal
from urlparse import urlparse

from stats import Stats
from coalescer import CoalescingMachine

from mozillapulse.config import PulseConfiguration
from mozillapulse.consumers import GenericConsumer


class StateError(Exception):
    pass


log = None

class Options(object):

    options = {}

    def __init__(self):
        self._parse_env()

    def _parse_env(self):
        try:
            self.options['user'] = os.environ['PULSE_USER']
            self.options['passwd'] = os.environ['PULSE_PASSWD']
            self.options['redis'] = urlparse(os.environ['REDIS_URL'])
        except KeyError:
            traceback.print_exc()
            sys.exit(1)

class TcPulseConsumer(GenericConsumer):
    def __init__(self, exchanges, **kwargs):
        super(TcPulseConsumer, self).__init__(
            PulseConfiguration(**kwargs), exchanges, **kwargs)

    def listen(self, callback=None, on_connect_callback=None):
        while True:
            consumer = self._build_consumer(
                callback=callback,
                on_connect_callback=on_connect_callback
            )
            with consumer:
                self._drain_events_loop()

    def _drain_events_loop(self):
        while True:
            try:
                self.connection.drain_events(timeout=self.timeout)
            except socket.timeout:
                logging.warning("Timeout! Restarting pulse consumer.")
                try:
                    self.disconnect()
                except Exception:
                    logging.warning("Problem with disconnect().")
                break


class TaskEventApp(object):

    # ampq/pulse listener
    listener = None

    # State transitions
    # pending --> running
    #         \-> exception
    exchanges = ['exchange/taskcluster-queue/v1/task-pending',
                 'exchange/taskcluster-queue/v1/task-running',
                 'exchange/taskcluster-queue/v1/task-exception']

    # TODO: move these to args and env options
    # TODO: make perm coalescer service pulse creds
    consumer_args = {
        'applabel': 'releng-tc-coalesce',
        'topic': ['#', '#', '#'],
        'durable': True,
        'user': 'public',
        'password': 'public'
    }

    options = None

    # Coalesing machine
    coalescer = None

    def __init__(self, redis_prefix, options, stats, datastore):
        self.pf = redis_prefix
        self.options = options
        self.stats = stats
        self.rds = datastore
        self.coalescer = CoalescingMachine(redis_prefix,
                                           datastore,
                                           stats=stats)
        route_key = "route." + redis_prefix + "#"
        self.consumer_args['topic'] = [route_key] * len(self.exchanges)
        self.consumer_args['user'] = self.options['user']
        self.consumer_args['password'] = self.options['passwd']
        log.info("Binding to queue with route key: %s" % (route_key))
        self.listener = TcPulseConsumer(self.exchanges,
                                callback=self._route_callback_handler,
                                **self.consumer_args)

    def run(self):
        while True:
            try:
                self.listener.listen()
            except KeyboardInterrupt:
                # Handle both SIGTERM and SIGINT
                self._graceful_shutdown()
            except:
                traceback.print_exc()

    def _graceful_shutdown(self):
        log.info("Gracefully shutting down")
        log.info("Deleting Pulse queue")
        self.listener.delete_queue()
        sys.exit(1)

    def delete_queue(self):
        self._check_params()
        if not self.connection:
            self.connect()

        queue = self._create_queue()
        try:
            queue(self.connection).delete()
        except ChannelError as e:
            if e.message != 404:
                raise
        except:
            raise


    def _route_callback_handler(self, body, message):
        """
        Route call body and msg to proper callback handler
        """
        # Ignore tasks with non-zero runId (for now)
        if not body['runId'] == 0:
            message.ack()
            return

        taskState = body['status']['state']
        taskId = body['status']['taskId']
        # Extract first coalesce key that matches
        for route in message.headers['CC']:
            route = route[6:]
            if self.pf == route[:len(self.pf)]:
                coalesce_key = route[len(self.pf):]
                break
        if taskState == 'pending':
            self.coalescer.insert_task(taskId, coalesce_key)
        elif taskState == 'running' or taskState == 'exception':
            self.coalescer.remove_task(taskId, coalesce_key)
        else:
            raise StateError
        message.ack()
        self.stats.notch('total_msgs_handled')
        log.debug("taskId: %s (%s)" % (taskId, taskState))

def setup_log():
    global log
    log = logging.getLogger(__name__)
    lvl = logging.DEBUG if os.getenv('DEBUG', False) else logging.INFO
    log.setLevel(lvl)
    console_handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(formatter)
    log.addHandler(console_handler)
    return log


def main():
    setup_log()
    options = Options().options
    log.info("Starting Coalescing Service")

    # prefix for all redis keys and route key
    redis_prefix = "coalesce.v1."

    # setup redis object
    rds = redis.Redis(host=options['redis'].hostname,
                      port=options['redis'].port,
                      password=options['redis'].password)
    stats = Stats(redis_prefix, datastore=rds)
    app = TaskEventApp(redis_prefix, options, stats, datastore=rds)
    signal.signal(signal.SIGTERM, signal_term_handler)
    app.run()
    # graceful shutdown via SIGTERM

def signal_term_handler(signal, frame):
    log.info("Handling signal: term")
    raise KeyboardInterrupt

if __name__ == '__main__':
    main()
