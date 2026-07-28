# Wikimedia OCR (https://gitlab.wikimedia.org/toolforge-repos/ocr), the
# same tool en.wikisource.org's OCR gadget calls (https://ocr.wmcloud.org),
# built here so tests can talk to a real instance instead of a fake one.
#
# Best-effort: this mirrors the install steps documented at
# https://wikitech.wikimedia.org/wiki/Nova_Resource:Wikisource/Wikimedia_OCR
# (Toolforge's own web-service scaffolding replaced with a plain Apache
# container) and has not been validated against a live build -- expect to
# need local fixes (package names / PHP version drift / repo layout changes
# upstream) the first time this actually runs. Only the free/local Tesseract
# engine is wired up; Google Vision and Transkribus need credentials this
# harness deliberately does not provide.

FROM php:8.2-apache

ARG OCR_REPO=https://gitlab.wikimedia.org/toolforge-repos/ocr.git
ARG OCR_REF=main

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      git unzip \
      tesseract-ocr tesseract-ocr-all \
      libicu-dev libcurl4-openssl-dev libonig-dev \
      curl gnupg; \
    docker-php-ext-install bcmath intl curl mbstring; \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -; \
    apt-get install -y --no-install-recommends nodejs; \
    curl -fsSL https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer; \
    rm -rf /var/lib/apt/lists/*

RUN a2enmod rewrite

RUN git clone --depth 1 --branch "$OCR_REF" "$OCR_REPO" /var/www/tool

WORKDIR /var/www/tool

# --no-dev/--production: this is a runtime image, not a dev checkout.
RUN composer install --no-dev --optimize-autoloader \
 && npm install && npm run build

COPY docker/wikimedia-ocr/apache-vhost.conf /etc/apache2/sites-available/000-default.conf
COPY docker/wikimedia-ocr/env.local /var/www/tool/.env.local

RUN chown -R www-data:www-data /var/www/tool

ENV APACHE_DOCUMENT_ROOT=/var/www/tool/public
EXPOSE 80

CMD ["apache2-foreground"]
