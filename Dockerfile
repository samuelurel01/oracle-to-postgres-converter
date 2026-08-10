FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ORACLE_CLIENT_DIR=/opt/oracle/instantclient

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip libaio1t64 \
    && mkdir -p /opt/oracle \
    && curl -fsSL https://download.oracle.com/otn_software/linux/instantclient/instantclient-basiclite-linuxx64.zip -o /tmp/instantclient.zip \
    && unzip -q /tmp/instantclient.zip -d /opt/oracle \
    && rm /tmp/instantclient.zip \
    && ln -s /opt/oracle/instantclient_* "$ORACLE_CLIENT_DIR" \
    && ln -s /usr/lib/x86_64-linux-gnu/libaio.so.1t64 /usr/lib/x86_64-linux-gnu/libaio.so.1 \
    && echo "$ORACLE_CLIENT_DIR" > /etc/ld.so.conf.d/oracle-instantclient.conf \
    && ldconfig \
    && apt-get purge -y --auto-remove curl unzip \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["oracle-to-postgres-web"]
