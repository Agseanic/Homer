# Homer Monitor

这是一个面向自建环境的轻量级监控面板，主要用于集中查看：

- Nginx 代理站点状态
- Docker 容器运行状态
- HTTPS 证书过期时间与续期状态
- 当前活跃告警

它适合部署在运维服务器、家庭实验室、公司内网或自托管平台中，用一个页面快速了解站点和服务的整体健康情况。

## 功能特性

- 自动发现 Nginx 代理站点
- 自动发现宿主机 Docker 容器
- 自动识别 HTTPS 证书过期时间和剩余天数
- 兼容常见自动续期方式，例如 `acme.sh`
- 显示网页与容器的关联关系
- 已关联网页的容器不在下方重复展示
- 点击“关联容器”可弹出详情
- 前端自动刷新状态数据
- 支持 Docker Compose 一键部署

## 技术栈

- 前端：HTML / CSS / JavaScript
- 采集器：Python
- 部署方式：Docker Compose
- Web 服务：Nginx

## 快速启动

```bash
cp .env.example .env
docker-compose up -d --build
```

默认访问地址：

```text
http://你的服务器IP:8088
```

## 工作原理

项目默认运行两个服务：

- `web`：负责提供监控页面
- `sync`：负责采集 Nginx、Docker、证书信息，并写入 `data/status.json`

前端页面会自动读取 `data/status.json`，并周期性刷新显示结果。

## 目录结构

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

## 配置说明

主配置文件：

```text
config/services.json
```

默认采用自动发现模式，会尝试：

- 扫描 Nginx 配置
- 扫描 Docker 容器
- 检测证书路径

你也可以通过手动配置做补充或覆盖，例如：

- 添加中文描述
- 修正自动发现结果
- 补充证书元信息

示例：

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

## 环境变量

示例 `.env`：

```env
HOMER_MONITOR_PORT=8088
MONITOR_SYNC_INTERVAL=30
MONITOR_TIMEOUT=3
MONITOR_CERT_WARNING_DAYS=30
DOCKER_API_VERSION=1.43
```

## Docker Compose 说明

为了实现自动发现，`sync` 容器需要读取宿主机的一些资源：

- Docker Socket
- Nginx 配置目录
- 证书目录
- `cron` 相关目录

如果你使用 `acme.sh` 管理证书，请确保 `docker-compose.yml` 中已经挂载：

```yaml
- /root/.acme.sh:/root/.acme.sh:ro
```

## 域名与 HTTPS

推荐使用方式：

1. 先通过 Docker Compose 在本地端口启动 Homer Monitor
2. 再通过宿主机 Nginx 反向代理公开域名，例如 `homer.example.com`
3. 使用 Let’s Encrypt 或 `acme.sh` 申请免费证书

## 页面交互说明

- 点击域名链接：直接打开对应网页
- 点击“关联容器”：查看该域名对应的容器详情
- 下方 Docker 列表仅显示未关联网页的容器

## 适用场景

- 内部运维总览页
- Nginx 反向代理监控页
- 自托管 Docker 服务监控面板
- HTTPS 证书巡检页面

## 部署手册

更详细的部署说明见：

```text
CONFIG_GUIDE.md
```

## License

你可以在这里补充自己的开源协议，例如 `MIT`。
