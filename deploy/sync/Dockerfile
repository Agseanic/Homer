FROM python:3.12-alpine

RUN apk add --no-cache bash docker-cli

WORKDIR /app

CMD ["bash", "/app/scripts/run-sync-daemon.sh"]
