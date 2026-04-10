# Homer Monitor Docker Compose 部署手册

这份手册按“尽量少折腾”的方式写，你把目录放到服务器后，基本按下面几步就能跑起来。

目标效果：

- 用 `docker compose` 自动部署
- 自动同步 Nginx 代理站点状态
- 自动同步 Docker 服务状态
- 自动读取 HTTPS 证书信息
- 用你的 Homer 域名访问页面

## 1. 放到服务器

建议目录：

`/opt/homer-monitor`

把整个项目目录放到服务器，例如：

```bash
mkdir -p /opt/homer-monitor
```

然后把这些内容放进去：

- `index.html`
- `styles.css`
- `app.js`
- `config/`
- `data/`
- `scripts/`
- `deploy/`
- `docker-compose.yml`
- `.env.example`

## 2. 复制环境变量文件

进入目录：

```bash
cd /opt/homer-monitor
cp .env.example .env
```

默认 `.env` 内容如下：

```env
HOMER_MONITOR_PORT=8088
MONITOR_SYNC_INTERVAL=30
MONITOR_TIMEOUT=3
MONITOR_CERT_WARNING_DAYS=30
```

一般先不用改。

## 3. 改配置文件

编辑：

`/opt/homer-monitor/config/services.json`

默认已经支持自动扫描，所以你不一定要把站点全手动写进去。  
你主要需要改这些内容：

- 你的真实域名
- 证书文件路径
- 需要补充的中文描述

如果你想先最简单跑起来，也可以先只保留：

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

这样会先靠自动扫描。

## 4. 一键启动

在服务器执行：

```bash
cd /opt/homer-monitor
docker compose up -d --build
```

启动后会有两个容器：

- `homer-monitor-web`
- `homer-monitor-sync`

其中：

- `web` 负责网页展示
- `sync` 负责定时采集状态

## 5. 查看运行状态

```bash
docker compose ps
docker compose logs -f sync
```

如果同步正常，你会看到类似：

```text
status synced to /app/data/status.json
```

## 6. 页面访问

默认访问地址：

`http://你的服务器IP:8088`

如果能打开，说明 compose 部署已经正常。

## 7. 绑定你的 Homer 域名

如果你要使用 Homer 域名，例如：

`homer.example.com`

只需要在宿主机 Nginx 上再做一层反向代理，把域名转发到 compose 里的 `8088` 端口。

示例：

```nginx
server {
    listen 80;
    server_name homer.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name homer.example.com;

    ssl_certificate /etc/letsencrypt/live/homer.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/homer.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8088;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

然后重载 Nginx：

```bash
nginx -t
systemctl reload nginx
```

完成后访问：

`https://homer.example.com`

## 8. compose 做了什么

`docker-compose.yml` 里有两个服务：

### `web`

- 基于 `nginx:alpine`
- 负责展示静态页面
- 自动读取 `data/status.json`

### `sync`

- 基于自带 Python 和 Docker CLI 的镜像
- 每隔一段时间执行一次采集脚本
- 自动读取宿主机：
  - Docker Socket
  - Nginx 配置目录
  - 证书目录

所以它才能做到自动发现：

- Nginx 站点
- Docker 容器
- 证书文件

## 9. 你要注意的挂载目录

Compose 里默认挂载了这些宿主机路径：

- `/var/run/docker.sock`
- `/etc/nginx`
- `/usr/local/etc/nginx`
- `/opt/homebrew/etc/nginx`
- `/etc/letsencrypt`

含义是：

- Linux 常见 Nginx 配置路径已经覆盖
- macOS Homebrew 路径也预留了

如果你的服务器不是这些路径，需要改：

`/opt/homer-monitor/docker-compose.yml`

## 10. 常用命令

启动：

```bash
docker compose up -d --build
```

停止：

```bash
docker compose down
```

重启：

```bash
docker compose restart
```

查看日志：

```bash
docker compose logs -f
docker compose logs -f sync
docker compose logs -f web
```

重新构建：

```bash
docker compose up -d --build
```

## 11. 自动刷新频率怎么改

改 `.env`：

```env
MONITOR_SYNC_INTERVAL=60
```

表示每 60 秒同步一次。

改完后执行：

```bash
docker compose up -d --build
```

## 12. 端口怎么改

改 `.env`：

```env
HOMER_MONITOR_PORT=9090
```

然后重新启动：

```bash
docker compose up -d --build
```

这样网页就会暴露在：

`http://服务器IP:9090`

## 13. 如果自动扫描不到

先看同步日志：

```bash
docker compose logs -f sync
```

如果有以下情况：

### Docker 扫描失败

通常是宿主机 Docker Socket 没挂成功，或者 Docker 本身不可用。

检查：

```bash
ls -l /var/run/docker.sock
docker ps
```

### Nginx 扫描失败

通常是宿主机 Nginx 配置不在默认路径。

这时你改：

`config/services.json`

里的：

`autoDiscovery.nginxConfigFiles`

把真实配置文件路径加进去。

### 证书读取失败

通常是：

- 域名本机不可达
- 443 端口不通
- 证书目录没挂对
- `localCertPath` 写错

## 14. 最省事的实际上线步骤

1. 把目录放到 `/opt/homer-monitor`
2. `cp .env.example .env`
3. 改 `config/services.json`
4. `docker compose up -d --build`
5. 浏览器访问 `http://服务器IP:8088`
6. 再给它配置 `homer.example.com` 反向代理

## 15. 你实际上只需要改这几个地方

- `.env` 里的端口
- `config/services.json` 里的域名和证书路径
- 你的宿主机 Nginx 里的 `server_name`
- 你的宿主机 Nginx 证书路径

## 16. 说明

这套 compose 已经比手动部署简单很多了，但有一个前提：

同步容器要读取宿主机的：

- Docker 信息
- Nginx 配置
- 证书目录

所以它必须挂这些宿主机目录。  
这是自动扫描方案必需的，不然容器内看不到宿主机服务信息。
