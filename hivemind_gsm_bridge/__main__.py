"""CLI entry point for the HiveMind <-> GSM modem bridge.

HiveMind identity (key/password/host/port) defaults to the values stored
by ``hivemind-client set-identity``; flags override them.
"""
import click
from ovos_utils.log import LOG

from hivemind_gsm_bridge import HiveMindGSMBridge


def connect_gsm_to_hivemind(serial_port, baudrate=115200, sim_pin=None,
                            key=None, password=None, host=None, port=5678,
                            self_signed=False, lang="en-us", site_id="gsm"):
    bridge = HiveMindGSMBridge(
        serial_port=serial_port, baudrate=baudrate, sim_pin=sim_pin,
        key=key, password=password, host=host, port=port,
        self_signed=self_signed, lang=lang, site_id=site_id,
    )
    bridge.start()
    return bridge


@click.command()
@click.option("--port", "serial_port", required=True,
              help="serial device the GSM modem is attached to, "
                   "e.g. /dev/ttyUSB0")
@click.option("--baud", "baudrate", type=int, default=115200,
              help="serial baud rate for the modem (default 115200)")
@click.option("--sim-pin", default=None, help="SIM card PIN, if required")
@click.option("--access-key", "key", default=None,
              help="HiveMind access key (default: from identity file)")
@click.option("--password", default=None,
              help="HiveMind password (default: from identity file)")
@click.option("--host", default=None,
              help="HiveMind host, e.g. ws://127.0.0.1 (default: from identity file)")
@click.option("--hivemind-port", "hive_port", type=int, default=5678,
              help="HiveMind port (default: 5678)")
@click.option("--site-id", default="gsm", help="this bridge's HiveMind site id")
@click.option("--self-signed", is_flag=True, help="accept self-signed SSL certificates")
@click.option("--lang", default="en-us", help="utterance language")
def main(serial_port, baudrate, sim_pin, key, password, host, hive_port,
         site_id, self_signed, lang):
    """Bridge a GSM/USB modem's SMS to a HiveMind node."""
    hive_host = host
    if hive_host and not hive_host.startswith("ws://") and not hive_host.startswith("wss://"):
        hive_host = "ws://" + hive_host

    LOG.info("bridge starting; press Ctrl-C to stop")
    bridge = None
    try:
        bridge = connect_gsm_to_hivemind(
            serial_port=serial_port, baudrate=baudrate, sim_pin=sim_pin,
            key=key, password=password, host=hive_host, port=hive_port,
            self_signed=self_signed, lang=lang, site_id=site_id,
        )
    except KeyboardInterrupt:
        LOG.info("shutting down")
    finally:
        if bridge is not None:
            bridge.stop()


if __name__ == '__main__':
    main()
