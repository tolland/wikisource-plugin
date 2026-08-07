FROM python:3.13-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y iproute2 curl telnet wget \
    && rm -rf /var/lib/apt/lists/*

RUN pip install \
    requests \
    mwparserfromhell \
    packaging \
    pywikibot

COPY docker/pywikibot/context ./
COPY docker/pywikibot/start-pywikibot.sh /usr/local/bin/start-pywikibot

RUN chmod +x /usr/local/bin/start-pywikibot

CMD ["start-pywikibot"]
