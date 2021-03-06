"""AMQP-Storm Base."""
__author__ = 'eandersson'

import time
import threading
from uuid import uuid4

from amqpstorm.exception import AMQPChannelError


IDLE_WAIT = 0.01
FRAME_MAX = 131072


class Stateful(object):
    """Stateful Class."""
    CLOSED = 0
    CLOSING = 1
    OPENING = 2
    OPEN = 3

    def __init__(self):
        self._state = self.CLOSED
        self._exceptions = []

    def set_state(self, state):
        """Set State.

        :param int state:
        :return:
        """
        self._state = state

    @property
    def is_closed(self):
        """Is Closed?

        :rtype: bool
        """
        return self._state == self.CLOSED

    @property
    def is_closing(self):
        """Is Closing?

        :rtype: bool
        """
        return self._state == self.CLOSING

    @property
    def is_opening(self):
        """Is Opening?

        :rtype: bool
        """
        return self._state == self.OPENING

    @property
    def is_open(self):
        """Is Open?

        :rtype: bool
        """
        return self._state == self.OPEN

    @property
    def exceptions(self):
        """Any exceptions thrown. This is useful for troubleshooting, and is
        used internally to check the health of the connection.

        :rtype: list
        """
        return self._exceptions

    def check_for_errors(self):
        """Check for critical errors.

        :return:
        """
        if self.exceptions:
            self.set_state(self.CLOSED)
            why = self.exceptions[0]
            raise why


class Rpc(object):
    """Rpc Class."""

    def __init__(self, adapter, timeout=360):
        """
        :param Stateful adapter: Connection or Channel.
        :param int timeout: Rpc timeout.
        """
        self.lock = threading.Lock()
        self.timeout = timeout
        self.response = {}
        self.request = {}
        self._adapter = adapter

    def on_frame(self, frame_in):
        """On RPC Frame.

        :param pamqp_spec.Frame frame_in: Amqp frame.
        :return:
        """
        if frame_in.name not in self.request:
            return False

        uuid = self.request[frame_in.name]
        self.response[uuid] = frame_in

        return True

    def register_request(self, valid_responses):
        """Register a RPC request.

        :param list valid_responses: List of possible Responses that
                                     we should be waiting for.
        :return:
        """
        uuid = str(uuid4())
        self.response[uuid] = None
        for action in valid_responses:
            self.request[action] = uuid

        return uuid

    def remove(self, uuid):
        """Remove any data related to a specific RPC request.

        :param str uuid: Rpc Identifier.
        :return:
        """
        self.remove_request(uuid)
        self.remove_response(uuid)

    def remove_request(self, uuid):
        """Remove any RPC request(s) using this uuid.

        :param str uuid: Rpc Identifier.
        :return:
        """
        if not uuid:
            return

        for key in list(self.request):
            if self.request[key] == uuid:
                del self.request[key]

    def remove_response(self, uuid):
        """Remove a RPC Response using this uuid.

        :param str uuid: Rpc Identifier.
        :return:
        """
        if not uuid:
            return

        if uuid in self.response:
            del self.response[uuid]

    def get_request(self, uuid, raw=False, auto_remove=True):
        """Get a RPC request.

        :param str uuid: Rpc Identifier
        :param bool raw: If enabled return the frame as is, else return
                         result as a dictionary.
        :param bool auto_remove: Automatically remove Rpc response.
        :return:
        """
        if uuid not in self.response:
            return

        self._wait_for_request(uuid)
        frame = self.response.get(uuid, None)

        self.response[uuid] = None
        if auto_remove:
            self.remove(uuid)

        result = None
        if raw:
            result = frame
        elif frame is not None:
            result = dict(frame)
        return result

    def _wait_for_request(self, uuid):
        """Wait for RPC request to arrive.

        :param str uuid: Rpc Identifier.
        :return:
        """
        start_time = time.time()
        while self.response[uuid] is None:
            self._adapter.check_for_errors()
            if time.time() - start_time > self.timeout:
                self._raise_rpc_timeout_error(uuid)
            time.sleep(IDLE_WAIT)

    def _raise_rpc_timeout_error(self, uuid):
        """Gather information and raise an Rpc exception.

        :param str uuid: Rpc Identifier.
        :return:
        """
        requests = []
        for key, value in self.request.items():
            if value == uuid:
                requests.append(key)
        self.remove(uuid)
        message = 'rpc requests {0!s} ({1!s}) took too long'
        raise AMQPChannelError(message.format(uuid, ', '.join(requests)))


class BaseChannel(object):
    """Base Channel Class."""

    def __init__(self, channel_id):
        self.lock = threading.Lock()
        self._consumer_tags = []
        self._channel_id = channel_id

    @property
    def channel_id(self):
        """Get Channel id.

        :rtype: int
        """
        return self._channel_id

    @property
    def consumer_tags(self):
        """Get a list of consumer tags.

        :rtype: list
        """
        return self._consumer_tags

    def add_consumer_tag(self, tag):
        """Add a Consumer tag.

        :param str tag: Consumer tag.
        :return:
        """
        if tag not in self._consumer_tags:
            self._consumer_tags.append(tag)

    def remove_consumer_tag(self, tag=None):
        """Remove a Consumer tag.

            If no tag is specified, all all tags will be removed.

        :param str tag: Consumer tag.
        :return:
        """
        if tag:
            if tag in self._consumer_tags:
                self._consumer_tags.remove(tag)
        else:
            self._consumer_tags = []
