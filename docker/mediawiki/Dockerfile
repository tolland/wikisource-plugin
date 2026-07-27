ARG MEDIAWIKI_VERSION=1.43
FROM mediawiki:${MEDIAWIKI_VERSION}

ARG PROOFREADPAGE_BRANCH=REL1_43

# djvulibre-bin + ghostscript give MediaWiki real DjVu handling (page count,
# per-page rendering, embedded text layer) -- without them an imported .djvu
# scan uploads but ProofreadPage cannot paginate an Index: from it.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      default-mysql-client git djvulibre-bin netpbm ghostscript; \
    rm -rf /var/lib/apt/lists/*; \
    git clone --depth 1 --branch "$PROOFREADPAGE_BRANCH" \
      https://gerrit.wikimedia.org/r/mediawiki/extensions/ProofreadPage \
      /var/www/html/extensions/ProofreadPage; \
    git clone --depth 1 --branch "$PROOFREADPAGE_BRANCH" \
      https://gerrit.wikimedia.org/r/mediawiki/extensions/TemplateStyles \
      /var/www/html/extensions/TemplateStyles

COPY docker/mediawiki/start-wikisource.sh /usr/local/bin/start-wikisource

RUN chmod +x /usr/local/bin/start-wikisource

CMD ["start-wikisource"]
