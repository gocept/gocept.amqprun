# coding: utf8
# Copyright (c) 2010 gocept gmbh & co. kg
# See also LICENSE.txt

import gocept.amqprun.testing
import os
import mock
import signal
import subprocess
import sys
import tempfile
import time
import zope.component


class TestMainWithQueue(gocept.amqprun.testing.MainTestCase):

    def test_message_should_be_processed(self):
        self.make_config(__name__, 'integration')
        self._queues.append('test.queue')
        self._queues.append('test.queue.error')
        self.create_reader()

        from gocept.amqprun.tests.integration import messages_received
        self.assertEquals([], messages_received)
        self.send_message('blarf', routing_key='test.routing')
        for i in range(100):
            if messages_received:
                break
        else:
            self.fail('Message was not received')
        self.assertEquals(1, len(messages_received))

    def test_technical_errors_should_not_crash(self):
        import gocept.amqprun.main
        self.make_config(__name__, 'integration')
        self._queues.append('test.queue')
        self._queues.append('test.queue.error')
        self.create_reader()

        self.reader = gocept.amqprun.main.main_reader

        from gocept.amqprun.tests.integration import messages_received
        self.assertEquals([], messages_received)
        self.send_message('blarf', routing_key='test.error')
        for i in range(100):
            if messages_received:
                break
        else:
            self.fail('Message was not received')
        self.assertEquals(1, len(messages_received))

    def test_rejected_messages_should_be_received_again_later(self):
        import gocept.amqprun.main
        self.make_config(__name__, 'integration')
        self._queues.append('test.queue')
        self._queues.append('test.queue.error')
        self.create_reader()
        self.reader = gocept.amqprun.main.main_reader
        self.reader.CHANNEL_LIFE_TIME = 1

        from gocept.amqprun.tests.integration import messages_received
        self.assertEqual([], messages_received)
        self.send_message('blarf', routing_key='test.error')
        for i in range(200):
            time.sleep(0.025)
            os.write(self.reader.connection.notifier_w, 'W')
            if len(messages_received) == 2:
                break
        else:
            self.fail('Message was not received again')

    @mock.patch('gocept.amqprun.server.MessageReader')
    @mock.patch('gocept.amqprun.worker.Worker')
    def test_basic_configuration_should_load_zcml(self, worker, reader):
        import gocept.amqprun.interfaces
        import gocept.amqprun.main
        config = self.make_config(__name__, 'basic')
        gocept.amqprun.main.main(config)
        self.assertEquals(1, reader.call_count)
        self.assertEquals(2, worker.call_count)
        utilities = list(zope.component.getUtilitiesFor(
            gocept.amqprun.interfaces.IHandlerDeclaration))
        self.assertEquals(1, len(utilities))
        self.assertEquals('basic', utilities[0][0])

    @mock.patch('gocept.amqprun.server.MessageReader')
    @mock.patch('gocept.amqprun.worker.Worker')
    def test_settings_should_be_available_through_utility(self, _1, _2):
        import gocept.amqprun.interfaces
        import gocept.amqprun.main
        config = self.make_config(__name__, 'settings')
        gocept.amqprun.main.main(config)
        settings = zope.component.getUtility(
            gocept.amqprun.interfaces.ISettings)
        self.assertEquals('foo', settings.get('test.setting.1'))
        self.assertEquals('bar', settings.get('test.setting.2'))

    @mock.patch('gocept.amqprun.server.MessageReader')
    @mock.patch('gocept.amqprun.worker.Worker')
    def test_settings_should_be_unicode(self, _1, _2):
        import gocept.amqprun.interfaces
        import gocept.amqprun.main
        config = self.make_config(__name__, 'settings')
        gocept.amqprun.main.main(config)
        settings = zope.component.getUtility(
            gocept.amqprun.interfaces.ISettings)
        self.assertIsInstance(settings.get('test.setting.1'), unicode)
        self.assertEquals(u'Ümläuten', settings.get('test.setting.unicode'))


class TestMainProcess(gocept.amqprun.testing.MainTestCase):

    def create_reader(self):
        self.make_config(__name__, 'process')
        script = tempfile.NamedTemporaryFile(suffix='.py')
        script.write("""
import sys
sys.path[:] = %(path)r
import gocept.amqprun.main
gocept.amqprun.main.main('%(config)s')
        """ % dict(path=sys.path, config=self.config.name))
        script.flush()
        self.log = tempfile.TemporaryFile()
        process = subprocess.Popen(
            [sys.executable, script.name],
            stdout=self.log, stderr=subprocess.STDOUT)
        time.sleep(1)
        self.pid = process.pid

    def test_sigterm_shuts_down_process_properly(self):
        self.create_reader()
        os.kill(self.pid, signal.SIGTERM)
        time.sleep(1)
        self.log.seek(0)
        self.assertIn('Received signal 15, terminating.', self.log.read())

    def test_sigint_shuts_down_process_properly(self):
        self.create_reader()
        os.kill(self.pid, signal.SIGINT)
        time.sleep(1)
        self.log.seek(0)
        self.assertIn('Received signal 2, terminating.', self.log.read())
