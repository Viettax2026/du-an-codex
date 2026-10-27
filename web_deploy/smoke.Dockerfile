# syntax=docker/dockerfile:1
FROM ubuntu:24.04
RUN --mount=type=secret,id=proxy_ca,required=true \
    apt-get -o Acquire::https::CaInfo=/run/secrets/proxy_ca update -qq && \
    DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::https::CaInfo=/run/secrets/proxy_ca install -y -qq python3-venv nginx curl ca-certificates xz-utils unzip openssl systemd && \
    rm -rf /var/lib/apt/lists/*
COPY zaloflow-web.zip /tmp/zaloflow-web.zip
RUN unzip -q /tmp/zaloflow-web.zip -d /tmp/source && \
    python3 /tmp/source/zaloflow-web/web_deploy/package.py install-code /tmp/source/zaloflow-web /opt/web-smoke
WORKDIR /opt/web-smoke
RUN --mount=type=secret,id=proxy_ca,required=true \
    CURL_CA_BUNDLE=/run/secrets/proxy_ca bash web_deploy/node-runtime.sh /opt/web-smoke/runtime/node && \
    python3 -m venv .venv && \
    PIP_CERT=/run/secrets/proxy_ca .venv/bin/python -m pip install -q -r requirements-prod.txt && \
    cd connector && PATH=/opt/web-smoke/runtime/node/bin:$PATH NODE_EXTRA_CA_CERTS=/run/secrets/proxy_ca ../runtime/node/bin/npm ci --omit=dev --no-audit --no-fund
RUN useradd --system --user-group --home-dir /opt/web-smoke --shell /usr/sbin/nologin web-smoke && \
    install -d -m 700 -o web-smoke -g web-smoke /opt/web-smoke/instance
CMD [".venv/bin/python", "web_deploy/container_smoke.py"]
