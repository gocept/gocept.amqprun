# Copyright (c) 2010 gocept gmbh & co. kg
# See also LICENSE.txt

import Queue
import logging
import threading
import transaction


log = logging.getLogger(__name__)


class Worker(threading.Thread):

    timeout = 5

    def __init__(self, queue, session_factory):
        self.queue = queue
        self.session_factory = session_factory
        self.running = False
        super(Worker, self).__init__()
        self.daemon = True

    def run(self):
        log.info('Starting worker')
        self.running = True
        while self.running:
            try:
                handler = self.queue.get(timeout=self.timeout)
            except Queue.Empty:
                pass
            else:
                try:
                    transaction.begin()
                    session = self.session_factory(handler)
                    try:
                        response = handler()
                        for msg in response:
                            session.send(msg)
                        transaction.commit()
                    except:
                        log.error("Error while processing message",
                                  exc_info=True)
                        transaction.abort()
                except:
                    log.error(
                        'Unhandled exception, prevent thread from crashing',
                        exc_info=True)

    def stop(self):
        log.info('Stopping worker.')
        self.running = False
        self.join()
