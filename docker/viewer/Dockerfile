FROM node:22-alpine

WORKDIR /app

COPY viewer/package.json viewer/package-lock.json ./
RUN npm ci

COPY viewer/ ./

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
