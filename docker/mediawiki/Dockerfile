ARG MEDIAWIKI_VERSION=1.43
FROM mediawiki:${MEDIAWIKI_VERSION}

ARG PROOFREADPAGE_BRANCH=REL1_43

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends default-mysql-client git; \
    rm -rf /var/lib/apt/lists/*; \
    git clone --depth 1 --branch "$PROOFREADPAGE_BRANCH" \
      https://gerrit.wikimedia.org/r/mediawiki/extensions/ProofreadPage \
      /var/www/html/extensions/ProofreadPage

COPY docker/mediawiki/start-wikisource.sh /usr/local/bin/start-wikisource

RUN chmod +x /usr/local/bin/start-wikisource

CMD ["start-wikisource"]
