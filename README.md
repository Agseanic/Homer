# Homer Monitor

Homer Monitor is a lightweight monitoring dashboard for self-hosted environments.

It is designed for teams that run websites behind Nginx and services in Docker, and want a simple page to check:

- Nginx proxy site status
- Docker container runtime status
- TLS certificate expiration and renewal status
- Active alerts in one place

The project supports automatic discovery of Nginx sites, Docker containers, and common certificate locations, and can be deployed with Docker Compose.

## Features

- Auto-discover Nginx proxy sites from Nginx config
- Auto-discover Docker containers from the host Docker daemon
- Detect HTTPS certificate expiration time and remaining days
- Recognize common auto-renew setups such as `acme.sh`
- Show linked website and container relationships
- Hide Docker services already linked to websites from the bottom list
- Open related container details in a modal dialog
- Refresh status automatically on the frontend

## Stack

- Frontend: plain HTML, CSS, JavaScript
- Collector: Python
- Deployment: Docker Compose
- Web serving: Nginx

## Quick Start

```bash
cp .env.example .env
docker-compose up -d --build
```

Default access:

```text
http://YOUR_SERVER_IP:8088
```

## How It Works

The project runs two services:

- `web`: serves the dashboard page
- `sync`: collects Nginx, Docker, and certificate data and writes `data/status.json`

The frontend reads `data/status.json` and updates automatically.

## Project Structure

```text
.
├── app.js
├── config/
│   └── services.json
├── data/
│   └── status.json
├── deploy/
│   ├── nginx/
│   └── sync/
├── docker-compose.yml
├── index.html
├── scripts/
│   ├── collect_status.py
│   ├── run-sync-daemon.sh
│   └── sync-status.sh
└── styles.css
```

## Configuration

Main config file:

```text
config/services.json
```

Default mode is automatic discovery:

- scan Nginx config
- scan Docker containers
- inspect certificate paths

You can still use manual overrides for:

- custom descriptions
- custom domain labels
- manual certificate metadata

Example:

```json
{
  "autoDiscovery": {
    "enabled": true,
    "nginxConfigFiles": [
      "/etc/nginx/nginx.conf",
      "/etc/nginx/conf.d/*.conf",
      "/etc/nginx/sites-enabled/*"
    ]
  },
  "proxies": [],
  "dockerServices": []
}
```

## Environment Variables

Example `.env`:

```env
HOMER_MONITOR_PORT=8088
MONITOR_SYNC_INTERVAL=30
MONITOR_TIMEOUT=3
MONITOR_CERT_WARNING_DAYS=30
DOCKER_API_VERSION=1.43
```

## Docker Compose Notes

The sync container needs access to host resources in order to auto-discover services:

- Docker socket
- Nginx config directories
- certificate directories
- cron files when renewal detection is needed

If you use `acme.sh`, make sure the compose file mounts:

```yaml
- /root/.acme.sh:/root/.acme.sh:ro
```

## Domain and HTTPS

Recommended setup:

1. Run Homer Monitor on a local port with Docker Compose
2. Use host Nginx to reverse proxy a public domain such as `homer.example.com`
3. Issue a free certificate with Let's Encrypt or `acme.sh`

## UI Behavior

- Clicking the website link opens the real website
- Clicking `关联容器` opens related container details
- The Docker list at the bottom only shows unlinked containers

## Common Use Cases

- Internal infrastructure overview page
- Nginx reverse proxy status page
- Self-hosted Docker service dashboard
- TLS certificate watch page

## Deployment Guide

A more detailed deployment guide is available in:

```text
CONFIG_GUIDE.md
```

## License

You can add your preferred license here, for example `MIT`.
