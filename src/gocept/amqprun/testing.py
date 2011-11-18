# Copyright (c) 2010 gocept gmbh & co. kg
# See also LICENSE.txt

import amqplib.client_0_8 as amqp
import asyncore
import datetime
import email.utils
import gocept.amqprun
import mock
import pkg_resources
import plone.testing
import plone.testing.zca
import signal
import string
import tempfile
import threading
import time
import unittest
import zope.component.testing
import zope.configuration.xmlconfig


ZCML_LAYER = plone.testing.zca.ZCMLSandbox(
    filename='configure.zcml', package=gocept.amqprun, module=__name__)


class QueueLayer(plone.testing.Layer):

    defaultBases = [ZCML_LAYER]

    def setUp(self):
        self['amqp-hostname'] = hostname = 'localhost'
        self['amqp-connection'] = amqp.Connection(host=hostname)
        self['amqp-channel'] = self['amqp-connection'].channel()

    def tearDown(self):
        self['amqp-channel'].close()
        self['amqp-connection'].close()

QUEUE_LAYER = QueueLayer()


class QueueTestCase(unittest.TestCase):

    layer = QUEUE_LAYER

    def setUp(self):
        super(QueueTestCase, self).setUp()
        self._queue_prefix = 'test.%f.' % time.time()
        self._queues = []
        self.connection = self.layer['amqp-connection']
        self.channel = self.layer['amqp-channel']

        self.receive_queue = self.get_queue_name('receive')
        self.channel.queue_declare(queue=self.receive_queue)
        self._queues.append(self.receive_queue)

    def tearDown(self):
        for queue_name in self._queues:
            try:
                # NOTE: we seem to need a new channel for each delete;
                # trying to use self.channel for all queues results in its
                # closing after the first delete
                with self.connection.channel() as channel:
                    channel.queue_delete(queue_name)
            except amqp.AMQPChannelException:
                pass
        super(QueueTestCase, self).tearDown()

    def get_queue_name(self, suffix):
        queue_name = self._queue_prefix + suffix
        self._queues.append(queue_name)
        return queue_name

    def send_message(self, body, routing_key=''):
        self.channel.basic_publish(
            amqp.Message(body, timestamp=datetime.datetime.now(),
                         msgid=email.utils.make_msgid('gocept.amqprun.test')),
            'amq.topic', routing_key=routing_key)
        time.sleep(0.1)

    def expect_response_on(self, routing_key):
        self.channel.queue_bind(
            self.receive_queue, 'amq.topic', routing_key=routing_key)

    def wait_for_response(self, timeout=100):
        """Wait for a response on `self.receive_queue`.

        timeout ... wait for n seconds.

        """
        for i in range(timeout):
            message = self.channel.basic_get(self.receive_queue, no_ack=True)
            if message:
                break
            time.sleep(1)
        else:
            self.fail('No message received')
        return message


class LoopTestCase(unittest.TestCase):

    def setUp(self):
        super(LoopTestCase, self).setUp()
        self.loop = None

    def tearDown(self):
        if self.loop is not None:
            self.loop.stop()
            self.thread.join()
        super(LoopTestCase, self).tearDown()
        self.assertEqual({}, asyncore.socket_map)

    def start_thread(self, loop):
        self.loop = loop
        self.thread = threading.Thread(target=self.loop.start)
        self.thread.start()
        for i in range(100):
            if self.loop.running:
                break
            time.sleep(0.025)
        else:
            self.fail('Loop did not start up.')


class MainTestCase(LoopTestCase, QueueTestCase):

    def setUp(self):
        import gocept.amqprun.worker
        super(MainTestCase, self).setUp()
        self._timeout = gocept.amqprun.worker.Worker.timeout
        gocept.amqprun.worker.Worker.timeout = 0.05
        self.orig_signal = signal.signal
        signal.signal = mock.Mock()
        plone.testing.zca.pushGlobalRegistry()

    def tearDown(self):
        import gocept.amqprun.worker
        for t in list(threading.enumerate()):
            if isinstance(t, gocept.amqprun.worker.Worker):
                t.stop()
        signal.signal = self.orig_signal
        plone.testing.zca.popGlobalRegistry()
        super(MainTestCase, self).tearDown()
        gocept.amqprun.worker.Worker.timeout = self._timeout

    def create_reader(self):
        import gocept.amqprun.main
        self.thread = threading.Thread(
            target=gocept.amqprun.main.main, args=(self.config.name,))
        self.thread.start()
        for i in range(100):
            if (gocept.amqprun.main.main_reader is not None and
                gocept.amqprun.main.main_reader.running):
                break
            time.sleep(0.025)
        else:
            self.fail('Reader did not start up.')
        self.loop = gocept.amqprun.main.main_reader

    def make_config(self, package, name, mapping=None):
        zcml_base = string.Template(
            unicode(pkg_resources.resource_string(package, '%s.zcml' % name),
                    'utf8'))
        self.zcml = tempfile.NamedTemporaryFile()
        self.zcml.write(zcml_base.substitute(mapping).encode('utf8'))
        self.zcml.flush()

        sub = dict(site_zcml=self.zcml.name)
        if mapping:
            sub.update(mapping)

        base = string.Template(
            unicode(pkg_resources.resource_string(package, '%s.conf' % name),
                    'utf8'))
        self.config = tempfile.NamedTemporaryFile()
        self.config.write(base.substitute(sub).encode('utf8'))
        self.config.flush()
        return self.config.name

    def wait_for_response(self, timeout=100):
        for i in range(100):
            if not self.loop.tasks.qsize():
                break
            time.sleep(0.05)
        else:
            self.fail('Message was not processed.')
        return super(MainTestCase, self).wait_for_response(timeout)


class Config(object):

    heartbeat_interval = 0
    hostname = NotImplemented
    password = None
    port = None
    username = None
    virtual_host = "/"

    def __init__(self, **kw):
        self.__dict__.update(kw)


class ConnectorHelper(object):

    def create_sender(self, **kw):
        import gocept.amqprun.sender
        return self._create_connector(gocept.amqprun.sender.MessageSender, **kw)

    def create_reader(self, **kw):
        import gocept.amqprun.server
        return self._create_connector(gocept.amqprun.server.MessageReader, **kw)

    def _create_connector(self, class_, **kw):
        params = dict(hostname=self.layer['amqp-hostname'])
        params.update(kw)
        return class_(Config(**params))
