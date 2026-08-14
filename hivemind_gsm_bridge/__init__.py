"""HiveMind <-> GSM modem SMS bridge.

A HiveMind bridge is a satellite whose input and output are a chat
platform instead of a microphone. This one talks to a physical GSM/USB
modem over a serial port with ``python-gsmmodem-new``: inbound SMS
received by the modem is forwarded onto the HiveMind bus, and the hub's
``speak`` reply is sent back as an SMS to the original sender.

Connection lifecycle, spelled out because getting it wrong is the
recurring bug across every HiveMind bridge written so far:

- ``HiveMessageBusClient.connect()`` already starts and owns the
  reconnect worker in a background thread, and blocks synchronously
  until the handshake completes (or fails). Call it exactly once. Do
  not also call ``run_forever()`` afterwards -- there is nothing left
  to start, the connection is already live in its own thread.
- Nothing is forwarded to HiveMind before ``connect()`` returns.
- host/port are configuration, not constants.
- a freshly registered HiveMind client is denied every message type
  until a hub admin runs ``hivemind-core allow-msg
  recognizer_loop:utterance <client_id>`` (and usually ``speak`` too);
  this bridge cannot do that step itself. See the README.
"""
from typing import Optional

from hivemind_bus_client import (
    HiveMessage,
    HiveMessageType,
    HiveMessageBusClient,
)
from ovos_bus_client.message import Message
from ovos_utils.log import LOG

platform = "HiveMindGSMBridgeV0.1"


class HiveMindGSMBridge:
    """Bridge a physical GSM/USB modem's SMS to a HiveMind node."""

    def __init__(self,
                 serial_port: Optional[str] = None,
                 baudrate: int = 115200,
                 sim_pin: Optional[str] = None,
                 key: Optional[str] = None,
                 password: Optional[str] = None,
                 host: Optional[str] = None,
                 port: int = 5678,
                 self_signed: bool = False,
                 lang: str = "en-us",
                 site_id: str = "gsm",
                 *,
                 client: Optional[HiveMessageBusClient] = None,
                 modem=None):
        """
        Parameters
        ----------
        serial_port: serial device the modem is attached to, e.g.
            ``/dev/ttyUSB0``. Required unless ``modem`` is injected
            (tests).
        baudrate: serial baud rate for the modem (default 115200).
        sim_pin: SIM card PIN, if the SIM requires one.
        key, password, host, port, self_signed: HiveMind hub connection.
        lang: default utterance language tag.
        site_id: this bridge's HiveMind site id.
        client: pre-built HiveMessageBusClient (tests / advanced setups).
            NOTE: HiveMessageBusClient does NOT open a connection in
            __init__ -- call connect_hivemind() to connect.
        modem: pre-built ``gsmmodem.modem.GsmModem`` (tests). When not
            given, one is built from serial_port/baudrate/sim_pin.
        """
        if modem is None and not serial_port:
            raise ValueError("serial_port is required unless a modem is injected")

        self.serial_port = serial_port
        self.baudrate = baudrate
        self.sim_pin = sim_pin
        self.lang = lang
        self.site_id = site_id

        self._modem = modem

        self.client = client or HiveMessageBusClient(
            key=key,
            password=password,
            host=host,
            port=port,
            useragent=platform,
            self_signed=self_signed,
        )
        self._connected = False

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    @property
    def modem(self):
        if self._modem is None:
            from gsmmodem.modem import GsmModem
            self._modem = GsmModem(self.serial_port, self.baudrate,
                                   smsReceivedCallbackFunc=self.handle_incoming_sms)
        return self._modem

    def connect_hivemind(self) -> None:
        """Connect to the HiveMind hub and wait for the handshake.

        Calls ``HiveMessageBusClient.connect()`` exactly once; that call
        already starts and owns the reconnect worker thread. Never call
        ``run_forever()`` in addition to this.
        """
        self.client.connect(site_id=self.site_id)
        self.client.on_mycroft("speak", self.handle_speak)
        self.client.on_mycroft("hive.complete_intent_failure",
                               self.handle_intent_failure)
        self._connected = True
        LOG.info("== connected to HiveMind")
        LOG.warning(
            "a freshly registered HiveMind client is denied every message "
            "type until an admin runs `hivemind-core allow-msg "
            "recognizer_loop:utterance <client_id>` on the hub (and "
            "usually `speak` too). If messages seem to vanish silently, "
            "check that first."
        )

    def start(self) -> None:
        """Connect to HiveMind, then bring the modem up and listen for SMS.

        Blocks the calling thread (the modem's serial read loop runs on
        its own worker thread once connected; this call just keeps the
        process alive).
        """
        self.connect_hivemind()
        self.modem.connect(self.sim_pin)
        LOG.info("== listening on GSM modem")
        try:
            self.modem.rxThread.join()
        except AttributeError:
            # some gsmmodem versions expose no public rx thread handle;
            # callers embedding this bridge should drive their own loop.
            pass

    def stop(self) -> None:
        try:
            self.modem.close()
        except Exception:
            LOG.exception("error closing GSM modem")
        try:
            self.client.close()
        except Exception:
            LOG.exception("error closing HiveMind client")
        self._connected = False

    # ------------------------------------------------------------------
    # GSM -> HiveMind
    # ------------------------------------------------------------------
    def handle_incoming_sms(self, sms) -> None:
        """Callback the modem library invokes for each received SMS.

        ``sms`` is a ``gsmmodem.modem.ReceivedSms``-like object with
        ``.number`` (sender) and ``.text`` attributes.
        """
        text = getattr(sms, "text", None)
        number = getattr(sms, "number", None)
        if not text or not text.strip() or not number:
            return

        if not self._connected:
            LOG.warning("dropping SMS from %s, not connected to HiveMind yet", number)
            return

        self.forward_to_hivemind(text, number)

    def forward_to_hivemind(self, text: str, from_number: str) -> None:
        msg = Message(
            "recognizer_loop:utterance",
            {"utterances": [text], "lang": self.lang},
            {
                "source": platform,
                "destination": "HiveMind",
                "platform": platform,
                "from_number": from_number,
                "user": {"phone_number": from_number},
                "session": {"session_id": f"gsm-{from_number}"},
            },
        )
        self.client.emit(HiveMessage(HiveMessageType.BUS, msg))

    # ------------------------------------------------------------------
    # HiveMind -> GSM
    # ------------------------------------------------------------------
    def handle_speak(self, message: Message) -> None:
        to_number = message.context.get("from_number")
        if to_number is None:
            return
        utterance = message.data.get("utterance")
        if not utterance:
            return
        self.send_sms(utterance, to_number)

    def handle_intent_failure(self, message: Message) -> None:
        to_number = message.context.get("from_number")
        if to_number is None:
            return
        LOG.error("complete intent failure")
        self.send_sms("I don't know how to answer that", to_number)

    def send_sms(self, text: str, to_number: str) -> None:
        """Send ``text`` back to ``to_number`` through the GSM modem.

        Called from the HiveMind bus's own worker thread; ``sendSms`` is
        a blocking call that talks to the modem over the serial port and
        waits for delivery confirmation from the network.
        """
        LOG.debug(f"Sending SMS to {to_number}: {text}")
        try:
            self.modem.sendSms(to_number, text)
        except Exception:
            LOG.exception(f"failed to send SMS to {to_number}")


__all__ = ["HiveMindGSMBridge", "platform"]
