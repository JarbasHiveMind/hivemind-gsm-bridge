FROM python:3.14-slim

WORKDIR /app
COPY . /app

# force the current hivemind-bus-client alpha rather than whatever a stale
# base layer might already have cached, since this bridge depends on the
# run_forever()-after-connect() fix and the current identity/handshake API
RUN pip install --no-cache-dir --upgrade "hivemind-bus-client>=1.0.13a1" \
    && pip install --no-cache-dir .

# credentials are passed as environment variables at `docker run` /
# compose time, never baked into the image.
#
# NOTE: this bridge needs a physical GSM/USB modem passed through to the
# container, e.g. `docker run --device=/dev/ttyUSB0 ...`. It cannot work
# against a modem that only exists on the host.
ENV HIVEMIND_HOST=ws://127.0.0.1 \
    HIVEMIND_PORT=5678 \
    HIVEMIND_SITE_ID=gsm \
    HIVEMIND_LANG=en-us \
    GSM_PORT=/dev/ttyUSB0 \
    GSM_BAUD=115200

ENTRYPOINT ["sh", "-c", "exec hivemind-gsm-bridge \
  --port \"$GSM_PORT\" \
  --baud \"$GSM_BAUD\" \
  --sim-pin \"$SIM_PIN\" \
  --access-key \"$HIVEMIND_ACCESS_KEY\" \
  --password \"$HIVEMIND_PASSWORD\" \
  --host \"$HIVEMIND_HOST\" \
  --hivemind-port \"$HIVEMIND_PORT\" \
  --site-id \"$HIVEMIND_SITE_ID\" \
  --lang \"$HIVEMIND_LANG\" \
  $EXTRA_ARGS"]
