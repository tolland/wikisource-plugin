FROM node:22-alpine

WORKDIR /app

COPY viewer/package.json viewer/package-lock.json ./
RUN npm ci

COPY viewer/ ./

COPY docker/viewer/start-viewer.sh /usr/local/bin/start-viewer
RUN chmod +x /usr/local/bin/start-viewer

EXPOSE 5173

CMD ["start-viewer"]
