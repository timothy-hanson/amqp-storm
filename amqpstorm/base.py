""" AMQP-Storm Base. """
__author__ = 'eandersson'

import time
import threading
from uuid import uuid4

from amqpstorm.exception import AMQPChannelError


IDLE_WAIT = 0.01
FRAME_MAX = 131072


class Stateful(object):
    """ Stateful Class. """
    CLOSED = 0
    CLOSING = 1
    OPENING = 2
    OPEN = 3

    def __init__(self):
        self._state = self.CLOSED
        self._exceptions = []

    def set_state(self, state):
        """ Set State.

        :param int state:
        :return:
        """
        self._state = state

    @property
    def is_closed(self):
        """ Is Closed?

        :rtype: bool
        """
        return self._state == self.CLOSED

    @property
    def is_closing(self):
        """ Is Closing?

        :rtype: bool
        """
        return self._state == self.CLOSING

    @property
    def is_opening(self):
        """ Is Opening?

        :rtype: bool
        """
        return self._state == self.OPENING

    @property
    def is_open(self):
        """ Is Open?

        :rtype: bool
        """
        return self._state == self.OPEN

    @property
    def exceptions(self):
        """ Any exceptions thrown. This is useful for troubleshooting, and is
            used internally to check the health of the connection.

        :rtype: list
        """
        return self._exceptions

    def check_for_errors(self):
        """ Check for critical errors.

        :return:
        """
        if self.exceptions:
            self.set_state(self.CLOSED)
            why = self.exceptions[0]
            raise why


class Rpc(object):
    """ Rpc Class. """

    def __init__(self, adapter):
        self.lock = threading.Lock()
        self.response = {}
        self.request = {}
        self._adapter = adapter

    def on_frame(self, frame_in):
        """ On RPC Frame.

        :param frame_in:
        :return:
        """
        if frame_in.name not in self.request:
            return False

        uuid = self.request[frame_in.name]
        self.response[uuid] = frame_in
        self.remove_request(uuid)
        return True

    def register_request(self, frame_out):
        """ Register a RPC request.

        :param Frame|str frame_out:
        :return:
        """
        uuid = str(uuid4())
        self.response[uuid] = None
        if isinstance(frame_out, str):
            valid_responses = [frame_out]
        else:
            valid_responses = frame_out.valid_responses

        if len(valid_responses) == 1:
            self.request[valid_responses[0]] = uuid
        else:
            for action in valid_responses:
                self.request[action] = uuid

        return uuid

    def remove_request(self, uuid):
        """ Remove any RPC request(s) from this uuid.

        :param str uuid:
        :return:
        """
        for key in self.request.keys():
            if self.request[key] == uuid:
                del self.request[key]

    def get_request(self, uuid, raw=False, timeout=30):
        """ Get a RPC request.

        :param str uuid:
        :param bool raw: Return the raw frame?
        :param int timeout: Rpc timeout.
        :return:
        """
        self._wait_for_request(uuid, timeout)
        frame = self.response.get(uuid, None)
        del self.response[uuid]

        result = None
        if raw:
            result = frame
        elif frame is not None:
            result = frame.__dict__
        return result

    def _wait_for_request(self, uuid, timeout):
        """ Wait for RPC request to arrive.

        :param str uuid:
        :param int timeout:
        :return:
        """
        start_time = time.time()
        while self.response[uuid] is None:
            self._adapter.check_for_errors()
            if time.time() - start_time > timeout:
                raise AMQPChannelError('rpc request took too long')
            time.sleep(IDLE_WAIT)


class BaseChannel(Stateful):
    """ Base Channel Class. """

    def __init__(self, channel_id):
        super(BaseChannel, self).__init__()
        self.lock = threading.Lock()
        self._consumer_tags = []
        self._channel_id = channel_id

    @property
    def channel_id(self):
        """ Get Channel id.

        :rtype: int
        """
        return self._channel_id

    @property
    def consumer_tags(self):
        """ Get a list of consumer tags.

        :rtype: list
        """
        return self._consumer_tags

    def add_consumer_tag(self, tag):
        """ Add a Consumer tag.

        :param str tag:
        :return:
        """
        if tag not in self._consumer_tags:
            self._consumer_tags.append(tag)

    def remove_consumer_tag(self, tag=None):
        """ Remove a Consumer tag.

            If no tag is specified, all all tags will be removed.

        :param str tag:
        :return:
        """
        if tag:
            if tag in self._consumer_tags:
                self._consumer_tags.remove(tag)
        else:
            self._consumer_tags = []