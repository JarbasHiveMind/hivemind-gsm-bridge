"""Unit tests: construct the bridge offline and drive it with mocks.

No live GSM modem or HiveMind connection is made. A pre-built mock
gsmmodem.modem.GsmModem and a pre-built mock HiveMessageBusClient are
injected so the bridge never touches a serial port or the network.
"""
from unittest.mock import MagicMock

import pytest


def _make_bridge(**kwargs):
    from hivemind_gsm_bridge import HiveMindGSMBridge

    fake_client = MagicMock(name="HiveMessageBusClient")
    fake_modem = MagicMock(name="GsmModem")

    bridge = HiveMindGSMBridge(client=fake_client, modem=fake_modem, **kwargs)
    return bridge, fake_client, fake_modem


def _fake_sms(text="turn on the lights", number="+15551234567"):
    sms = MagicMock()
    sms.text = text
    sms.number = number
    return sms


def test_import_package_and_version():
    import hivemind_gsm_bridge
    from hivemind_gsm_bridge.version import __version__

    assert isinstance(__version__, str)
    assert __version__
    assert hivemind_gsm_bridge.platform.startswith("HiveMindGSMBridge")


def test_construct_bridge_without_connecting():
    bridge, fake_client, fake_modem = _make_bridge()
    assert bridge._connected is False
    fake_client.connect.assert_not_called()
    fake_modem.connect.assert_not_called()


def test_serial_port_required_without_injected_modem():
    from hivemind_gsm_bridge import HiveMindGSMBridge

    with pytest.raises(ValueError):
        HiveMindGSMBridge(client=MagicMock())


def test_connect_hivemind_calls_connect_once_and_registers_handlers():
    """connect_hivemind() must call connect() exactly once, never run_forever()."""
    bridge, fake_client, fake_modem = _make_bridge()
    bridge.connect_hivemind()

    fake_client.connect.assert_called_once_with(site_id="gsm")
    fake_client.run_forever.assert_not_called()
    assert bridge._connected is True
    registered = {call.args[0] for call in fake_client.on_mycroft.call_args_list}
    assert registered == {"speak", "hive.complete_intent_failure"}


def test_inbound_sms_forwarded_to_hivemind_after_connect():
    from hivemind_bus_client import HiveMessage, HiveMessageType

    bridge, fake_client, fake_modem = _make_bridge()
    bridge.connect_hivemind()

    bridge.handle_incoming_sms(_fake_sms(text="turn on the lights", number="+15551234567"))

    fake_client.emit.assert_called_once()
    sent = fake_client.emit.call_args[0][0]
    assert isinstance(sent, HiveMessage)
    assert sent.msg_type == HiveMessageType.BUS
    payload = sent.payload
    assert payload.msg_type == "recognizer_loop:utterance"
    assert payload.data["utterances"] == ["turn on the lights"]
    assert payload.context["from_number"] == "+15551234567"
    assert payload.context["session"]["session_id"] == "gsm-+15551234567"


def test_no_forward_before_hivemind_connected():
    bridge, fake_client, fake_modem = _make_bridge()
    # deliberately not calling bridge.connect_hivemind()

    bridge.handle_incoming_sms(_fake_sms())

    fake_client.emit.assert_not_called()


def test_empty_text_is_ignored():
    bridge, fake_client, fake_modem = _make_bridge()
    bridge.connect_hivemind()

    bridge.handle_incoming_sms(_fake_sms(text="   "))

    fake_client.emit.assert_not_called()


def test_missing_number_is_ignored():
    bridge, fake_client, fake_modem = _make_bridge()
    bridge.connect_hivemind()

    bridge.handle_incoming_sms(_fake_sms(number=None))

    fake_client.emit.assert_not_called()


def test_speak_sends_sms_to_originating_number():
    from ovos_bus_client.message import Message

    bridge, fake_client, fake_modem = _make_bridge()
    msg = Message("speak", {"utterance": "hi there"}, {"from_number": "+15551234567"})
    bridge.handle_speak(msg)

    fake_modem.sendSms.assert_called_once_with("+15551234567", "hi there")


def test_speak_with_no_from_number_is_ignored():
    from ovos_bus_client.message import Message

    bridge, fake_client, fake_modem = _make_bridge()
    msg = Message("speak", {"utterance": "hi"}, {})
    bridge.handle_speak(msg)
    fake_modem.sendSms.assert_not_called()


def test_intent_failure_sends_fallback_sms():
    from ovos_bus_client.message import Message

    bridge, fake_client, fake_modem = _make_bridge()
    msg = Message("hive.complete_intent_failure", {}, {"from_number": "+15551234567"})
    bridge.handle_intent_failure(msg)

    fake_modem.sendSms.assert_called_once()
    args, _ = fake_modem.sendSms.call_args
    assert args[0] == "+15551234567"
    assert "don't know" in args[1]


def test_send_sms_exception_is_caught():
    bridge, fake_client, fake_modem = _make_bridge()
    fake_modem.sendSms.side_effect = RuntimeError("modem timeout")

    bridge.send_sms("hello", "+15551234567")  # must not raise
