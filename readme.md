# HiveMind GSM Bridge

This bridges SMS sent to a physical GSM/USB modem to a HiveMind node. A
HiveMind bridge is a satellite whose input and output are a chat
platform instead of a microphone: SMS received by the modem become
HiveMind utterances, and the hub's spoken replies are sent back as SMS
to the original sender.

This bridge needs real hardware: a GSM/USB modem and a SIM card that can
send and receive SMS. It has not been exercised against a live modem or
a real HiveMind hub — only unit-tested with both sides mocked.

## Hardware you need

- A USB GSM/GPRS modem with AT-command support. Cheap, widely available
  modules that are known to work with the underlying `python-gsmmodem`
  library family: Huawei E169/E220/E3131 USB sticks, and standalone
  AT-command modems built around SIM800/SIM900 chipsets (e.g. many
  "SIM800L USB to serial" boards). Avoid modems locked to a single
  carrier's dongle software (some Huawei/ZTE sticks ship in
  "mass-storage first" mode and need `usb_modeswitch` to expose the
  modem interface at all — check the modem's exact model before buying).
- A SIM card, activated with an SMS-capable plan, inserted into the
  modem. A prepaid SIM is enough for testing.

## Finding the serial device

Plug the modem in, then check what device node Linux assigned it:

```bash
dmesg | tail -20
ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null
```

Most USB GSM modems expose more than one serial interface (e.g. modem
control, diagnostics, and the AT-command port); the AT-command port is
usually the one that responds to `AT` when you talk to it directly:

```bash
sudo apt install minicom  # or screen
minicom -D /dev/ttyUSB2 -b 115200
# type AT and press enter; a modem that responds sends back "OK"
```

If nothing responds, try the other `/dev/ttyUSB*` nodes the modem
created. Once you have the right device, pass it as `--port`.

## Registering the bridge on the hub

Every HiveMind client needs credentials and, separately, permission to
send the message types it uses. On the machine running `hivemind-core`:

```bash
hivemind-core add-client
```

This prints an access key and password; pass them to the bridge as
`--access-key` / `--password` (or store them once with
`hivemind-client set-identity` and omit the flags).

A freshly added client is denied every message type by default. The
bridge needs at least:

```bash
hivemind-core allow-msg recognizer_loop:utterance <client_id>
hivemind-core allow-msg speak <client_id>
```

`<client_id>` is printed by `add-client` (and by `hivemind-core
list-clients` afterwards). Skipping this step is the single most common
reason a bridge "connects fine" but nothing ever seems to happen: the
hub silently drops every message the client sends until it is
whitelisted.

## Running the bridge

```bash
pip install .
hivemind-gsm-bridge \
  --port /dev/ttyUSB2 --baud 115200 \
  --access-key <key> --password <password> \
  --host ws://127.0.0.1 --hivemind-port 5678
```

If the SIM requires a PIN, pass `--sim-pin <pin>`.

Useful flags:

- `--site-id`: this bridge's HiveMind site id. If you run more than one
  bridge on the same host, give each a distinct site id — otherwise
  they collide over the same identity file and pinned peer keys.
- `--self-signed`: accept a self-signed TLS certificate on `wss://`
  hubs.
- `--lang`: the language tag attached to forwarded utterances (default
  `en-us`).

Note: `--port` is the serial device (e.g. `/dev/ttyUSB0`), and the
HiveMind hub's network port is `--hivemind-port` — the two are
deliberately named differently so they can never be confused on the
command line.

Run `hivemind-gsm-bridge --help` for the full list.

## Docker

The modem is a physical device and must be passed through to the
container:

```bash
docker build -t hivemind-gsm-bridge .
docker run --rm --device=/dev/ttyUSB2 \
  -e GSM_PORT=/dev/ttyUSB2 \
  -e HIVEMIND_ACCESS_KEY=... \
  -e HIVEMIND_PASSWORD=... \
  -e HIVEMIND_HOST=ws://hivemind-core \
  hivemind-gsm-bridge
```

or via `docker-compose.yml` — copy it, fill in the environment section
and device path, and `docker compose up`.

## What this bridge does, precisely

- Connects to a GSM modem over a serial port with
  `python-gsmmodem-new`'s `GsmModem`, registering a callback for
  incoming SMS.
- Connects to the HiveMind hub with
  `hivemind_bus_client.HiveMessageBusClient`.
- Drops empty or malformed SMS and anything received before the
  HiveMind handshake has completed — forwarding earlier would get the
  connection killed by the hub instead of just failing the one message.
- Forwards each remaining SMS as a `recognizer_loop:utterance` bus
  message, carrying the sender's phone number in the message context so
  the hub's `speak` reply can be routed back to the right number.
- Sends `speak` replies (and a fixed fallback line on
  `hive.complete_intent_failure`) back to the originating number through
  the modem's `sendSms`.

## Testing

```bash
pip install -e .[test]
pytest tests/
```

The test suite mocks both the modem object and the HiveMind
`HiveMessageBusClient`, so it runs without physical hardware or a live
hub. It has not been exercised against a real GSM modem or a real
HiveMind hub — that needs the actual hardware, which this repository
does not have.
