#!/usr/bin/env python3
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("MONITOR_CONFIG", ROOT / "config" / "services.json"))
OUTPUT_PATH = Path(os.environ.get("MONITOR_OUTPUT", ROOT / "data" / "status.json"))
SYNC_INTERVAL = int(os.environ.get("MONITOR_SYNC_INTERVAL", "30"))
REQUEST_TIMEOUT = float(os.environ.get("MONITOR_TIMEOUT", "3"))
CERT_WARNING_DAYS = int(os.environ.get("MONITOR_CERT_WARNING_DAYS", "30"))
TZ = timezone(timedelta(hours=8))


def load_config():
  with CONFIG_PATH.open("r", encoding="utf-8") as file:
    return json.load(file)


def run_command(command):
  try:
    result = subprocess.run(
      command,
      capture_output=True,
      text=True,
      check=False,
    )
  except FileNotFoundError:
    return None, "command-not-found"

  if result.returncode != 0:
    return None, result.stderr.strip() or result.stdout.strip() or f"exit-{result.returncode}"

  return result.stdout, None


def find_first(values):
  for value in values:
    if value:
      return value
  return None


def deep_merge(base, override):
  if not isinstance(base, dict) or not isinstance(override, dict):
    return override
  merged = dict(base)
  for key, value in override.items():
    if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
      merged[key] = deep_merge(merged[key], value)
    else:
      merged[key] = value
  return merged


def iso_now():
  return datetime.now(TZ).isoformat(timespec="seconds")


def format_dt(date):
  return date.astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S")


def parse_url(url):
  parsed = urlparse(url)
  scheme = parsed.scheme or "http"
  host = parsed.hostname or parsed.netloc or url
  port = parsed.port or (443 if scheme == "https" else 80)
  return scheme, host, port


def parse_simple_cron(expr):
  parts = expr.split()
  if len(parts) < 5:
    return None

  minute, hour, day, month, weekday = parts[:5]
  if minute.isdigit() and hour.isdigit() and day == "*" and month == "*" and weekday == "*":
    return f"每天 {int(hour):02d}:{int(minute):02d}"
  if minute.isdigit() and hour == "*" and day == "*" and month == "*" and weekday == "*":
    return f"每小时 {int(minute):02d} 分"
  if minute.isdigit() and hour.isdigit() and day == "*" and month == "*" and weekday.isdigit():
    names = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"]
    return f"{names[int(weekday) % 7]} {int(hour):02d}:{int(minute):02d}"
  return None


def read_text_file(path):
  try:
    return Path(path).read_text(encoding="utf-8", errors="ignore")
  except OSError:
    return ""


def detect_host_renew_schedule(cert_meta):
  renewal = cert_meta.get("autoRenew", {})
  if renewal.get("nextRunAt") or renewal.get("schedule"):
    return renewal.get("nextRunAt") or renewal.get("schedule")

  local_cert_path = cert_meta.get("localCertPath", "")
  acme_home = Path("/root/.acme.sh")
  if local_cert_path.startswith("/root/.acme.sh/") or acme_home.exists():
    cron_candidates = [
      "/etc/crontab",
      "/etc/cron.d/acme",
      "/etc/cron.d/acme.sh",
      "/var/spool/cron/root",
      "/var/spool/cron/crontabs/root",
    ]
    cron_texts = [read_text_file(path) for path in cron_candidates]
    for text in cron_texts:
      for line in text.splitlines():
        if "acme.sh" not in line or line.strip().startswith("#"):
          continue
        cron_match = re.match(r"\s*([\S]+\s+[\S]+\s+[\S]+\s+[\S]+\s+[\S]+)\s+", line)
        if cron_match:
          parsed = parse_simple_cron(cron_match.group(1))
          if parsed:
            return f"acme.sh {parsed}"
          return "acme.sh 定时续期"
      if text:
        return "acme.sh 自动续期"
    return "acme.sh 自动续期"

  return "--"


def has_auto_renew(schedule_text):
  if not schedule_text or schedule_text == "--":
    return False
  keywords = ["acme.sh", "自动", "每天", "每小时", "周"]
  return any(keyword in schedule_text for keyword in keywords)


def format_http_state(code):
  if code is None:
    return "请求失败"
  return f"{code} {'OK' if code < 400 else 'FAIL'}"


def map_proxy_status(code, latency_ms):
  if code is None:
    return "error"
  if 200 <= code < 400:
    return "warning" if latency_ms > 400 else "healthy"
  if 400 <= code < 500:
    return "warning"
  return "error"


def merge_statuses(*statuses):
  priority = {"error": 3, "warning": 2, "restarting": 2, "stopped": 3, "running": 0, "healthy": 0}
  highest = "healthy"
  for status in statuses:
    if priority.get(status, 1) > priority.get(highest, 1):
      highest = status
  return highest


def config_list():
  if CONFIG_PATH.exists():
    return load_config()
  return {}


def discover_nginx_raw_config(config):
  output, error = run_command(["nginx", "-T"])
  if output:
    return output

  auto = config.get("autoDiscovery", {})
  candidate_files = auto.get(
    "nginxConfigFiles",
    [
      "/etc/nginx/nginx.conf",
      "/etc/nginx/conf.d/default.conf",
      "/etc/nginx/conf.d/*.conf",
      "/etc/nginx/sites-enabled/*",
      "/usr/local/etc/nginx/nginx.conf",
      "/opt/homebrew/etc/nginx/nginx.conf",
    ],
  )

  file_text = []
  for pattern in candidate_files:
    output, _ = run_command(["/bin/sh", "-lc", f"for f in {pattern}; do [ -f \"$f\" ] && cat \"$f\"; done"])
    if output:
      file_text.append(output)
  return "\n".join(file_text)


def split_server_blocks(text):
  blocks = []
  marker = "server {"
  start = 0
  while True:
    idx = text.find(marker, start)
    if idx == -1:
      break
    depth = 0
    end = idx
    while end < len(text):
      char = text[end]
      if char == "{":
        depth += 1
      elif char == "}":
        depth -= 1
        if depth == 0:
          blocks.append(text[idx : end + 1])
          start = end + 1
          break
      end += 1
    else:
      break
  return blocks


def discover_nginx_proxies(config):
  raw = discover_nginx_raw_config(config)
  if not raw:
    return []

  proxies_by_host = {}
  for index, block in enumerate(split_server_blocks(raw), start=1):
    server_names_match = re.search(r"server_name\s+([^;]+);", block)
    proxy_pass_match = re.search(r"proxy_pass\s+(https?://[^;]+);", block)
    listen_lines = re.findall(r"listen\s+([^;]+);", block)
    cert_match = re.search(r"ssl_certificate\s+([^;]+);", block)
    if not server_names_match:
      continue

    names = [name for name in server_names_match.group(1).split() if name != "_"]
    if not names:
      continue
    host = names[0]
    listens_tls = any("443" in line or "ssl" in line for line in listen_lines)
    scheme = "https" if listens_tls else "http"
    target_path = "/"
    target = f"{scheme}://{host}{target_path}"
    if proxy_pass_match:
      target = f"{scheme}://{host}{target_path}"

    item = {
      "name": host.replace(".", "-"),
      "host": host,
      "description": "",
      "url": target,
      "dockerServices": [],
      "upstream": proxy_pass_match.group(1) if proxy_pass_match else "",
      "certificate": {
        "name": f"{host}-cert",
        "domain": host,
      },
    }

    if cert_match:
      item["certificate"]["localCertPath"] = cert_match.group(1)

    item["discovery"] = {
      "source": "nginx",
      "serverBlockIndex": index,
      "listen": listen_lines,
    }
    existing = proxies_by_host.get(host)
    if not existing:
      proxies_by_host[host] = item
      continue

    existing_scheme, _, _ = parse_url(existing["url"])
    current_scheme, _, _ = parse_url(item["url"])

    if existing_scheme != "https" and current_scheme == "https":
      item["dockerServices"] = existing.get("dockerServices", [])
      if not item.get("upstream"):
        item["upstream"] = existing.get("upstream", "")
      proxies_by_host[host] = item
      existing = item

    if not existing.get("upstream") and item.get("upstream"):
      existing["upstream"] = item["upstream"]
    if not existing.get("certificate", {}).get("localCertPath") and item.get("certificate", {}).get("localCertPath"):
      existing.setdefault("certificate", {})["localCertPath"] = item["certificate"]["localCertPath"]
    existing.setdefault("discovery", {}).setdefault("listen", [])
    existing["discovery"]["listen"] = sorted(set(existing["discovery"]["listen"] + listen_lines))

  return list(proxies_by_host.values())


def discover_docker_services():
  output, error = run_command(["docker", "ps", "-a", "--format", "{{json .}}"])
  if error:
    return {}, error

  services = {}
  for line in output.splitlines():
    if not line.strip():
      continue
    row = json.loads(line)
    name = row.get("Names")
    if not name:
      continue
    ports = row.get("Ports", "") or ""
    services[name] = {
      "name": name,
      "description": "自动发现的 Docker 服务",
      "sites": [],
      "detectedPorts": ports,
      "image": row.get("Image", "--"),
    }
  return services, None


def extract_host_port(url):
  if not url:
    return None
  parsed = urlparse(url)
  host = parsed.hostname
  port = parsed.port or (443 if parsed.scheme == "https" else 80)
  return host, port


def parse_port_mappings(port_text):
  mappings = []
  for token in [part.strip() for part in port_text.split(",") if part.strip()]:
    match = re.search(r"(?:(\d+\.\d+\.\d+\.\d+|\[::\]|::):)?(\d+)->(\d+)/(tcp|udp)", token)
    if match:
      mappings.append(
        {
          "hostPort": match.group(2),
          "containerPort": match.group(3),
          "protocol": match.group(4),
        }
      )
  return mappings


def auto_link_proxies_to_docker(proxies, docker_services):
  for proxy in proxies:
    upstream = proxy.get("upstream", "")
    upstream_host_port = extract_host_port(upstream)
    linked = []
    for service in docker_services.values():
      mappings = parse_port_mappings(service.get("detectedPorts", ""))
      if upstream_host_port:
        _, upstream_port = upstream_host_port
        if any(int(mapping["hostPort"]) == upstream_port or int(mapping["containerPort"]) == upstream_port for mapping in mappings):
          linked.append(service["name"])
      elif proxy.get("host") and any(site.get("url", "").find(proxy["host"]) >= 0 for site in service.get("sites", [])):
        linked.append(service["name"])
    proxy["dockerServices"] = sorted(set(proxy.get("dockerServices", []) + linked))


def merge_discovered_config(user_config):
  if not user_config.get("autoDiscovery", {}).get("enabled", True):
    return {
      "proxies": user_config.get("proxies", []),
      "dockerServices": user_config.get("dockerServices", []),
      "discoveryErrors": {},
    }

  discovered_proxies = discover_nginx_proxies(user_config)
  discovered_services, docker_error = discover_docker_services()

  manual_proxies = {item["name"]: item for item in user_config.get("proxies", [])}
  merged_proxies = []
  seen_proxy_names = set()

  for proxy in discovered_proxies:
    override = manual_proxies.get(proxy["name"]) or manual_proxies.get(proxy["host"])
    merged = deep_merge(proxy, override or {})
    merged_proxies.append(merged)
    seen_proxy_names.add(merged["name"])

  for name, item in manual_proxies.items():
    if item["name"] not in seen_proxy_names:
      merged_proxies.append(item)

  manual_services = {item["name"]: item for item in user_config.get("dockerServices", [])}
  merged_services = {}
  for name, service in discovered_services.items():
    merged_services[name] = deep_merge(service, manual_services.get(name, {}))
  for name, service in manual_services.items():
    if name not in merged_services:
      merged_services[name] = service

  for proxy in merged_proxies:
    for service_name in proxy.get("dockerServices", []):
      service = merged_services.setdefault(service_name, {"name": service_name, "description": "手动配置的 Docker 服务", "sites": []})
      if not any(site.get("url") == proxy["url"] for site in service.get("sites", [])):
        service.setdefault("sites", []).append(
          {
            "label": proxy.get("description") or proxy["host"],
            "url": proxy["url"].rsplit("/healthz", 1)[0],
            "proxy": proxy["name"],
          }
        )

  auto_link_proxies_to_docker(merged_proxies, merged_services)
  return {
    "proxies": merged_proxies,
    "dockerServices": list(merged_services.values()),
    "discoveryErrors": {
      "docker": docker_error,
    },
  }


def check_url(url):
  started = time.perf_counter()
  request = Request(url, headers={"User-Agent": "homer-monitor/1.0"})
  try:
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
      latency_ms = round((time.perf_counter() - started) * 1000)
      return response.getcode(), latency_ms, None
  except HTTPError as error:
    latency_ms = round((time.perf_counter() - started) * 1000)
    return error.code, latency_ms, str(error)
  except URLError as error:
    return None, None, str(error.reason)
  except Exception as error:
    return None, None, str(error)


def check_certificate(url, item):
  scheme, host, port = parse_url(url)
  cert_meta = item.get("certificate", {})
  renewal_meta = cert_meta.get("autoRenew", {})
  renew_schedule = detect_host_renew_schedule(cert_meta)

  result = {
    "name": cert_meta.get("name", item["name"]),
    "domain": cert_meta.get("domain", host),
    "status": "unknown",
    "description": cert_meta.get("description", item.get("description", "")),
    "metrics": {
      "证书域名": host,
      "过期时间": "--",
      "剩余天数": "--",
      "自动更新时间": renew_schedule,
      "上次续期": renewal_meta.get("lastRenewedAt") or "--",
      "检查时间": iso_now(),
    },
    "sourceUrl": url,
  }

  if scheme != "https":
    result["status"] = "neutral"
    result["metrics"]["证书域名"] = "非 HTTPS"
    return result, []

  context = ssl.create_default_context()
  alerts = []

  try:
    with socket.create_connection((host, port), timeout=REQUEST_TIMEOUT) as sock:
      with context.wrap_socket(sock, server_hostname=host) as secure_sock:
        certificate = secure_sock.getpeercert()
  except Exception as error:
    result["status"] = "error"
    result["metrics"]["证书域名"] = host
    alerts.append(
      {
        "title": f"{result['name']} 证书读取失败",
        "level": "error",
        "message": str(error),
      }
    )
    return result, alerts

  expires_raw = certificate.get("notAfter")
  if not expires_raw:
    result["status"] = "warning"
    alerts.append(
      {
        "title": f"{result['name']} 未返回证书过期时间",
        "level": "warning",
        "message": f"{host}:{port} 未返回可解析的 TLS 证书过期时间。",
      }
    )
    return result, alerts

  expires_at = datetime.strptime(expires_raw, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc).astimezone(TZ)
  remaining_days = (expires_at - datetime.now(TZ)).days
  result["metrics"]["过期时间"] = expires_at.isoformat(timespec="seconds")
  result["metrics"]["剩余天数"] = f"{remaining_days} 天"
  result["metrics"]["证书域名"] = ", ".join(
    value
    for _, subject in certificate.get("subjectAltName", [])
    for value in [subject]
  ) or host

  local_cert_path = cert_meta.get("localCertPath")
  if local_cert_path:
    try:
      cert_mtime = datetime.fromtimestamp(Path(local_cert_path).stat().st_mtime, TZ)
      result["metrics"]["上次续期"] = cert_mtime.isoformat(timespec="seconds")
    except FileNotFoundError:
      alerts.append(
        {
          "title": f"{result['name']} 本地证书文件不存在",
          "level": "warning",
          "message": local_cert_path,
        }
      )

  if remaining_days < 0:
    result["status"] = "error"
    alerts.append(
      {
        "title": f"{result['name']} 证书已过期",
        "level": "error",
        "message": f"{host} 的 TLS 证书已于 {expires_at.isoformat(timespec='seconds')} 过期。",
      }
    )
  elif remaining_days <= CERT_WARNING_DAYS and not has_auto_renew(renew_schedule):
    result["status"] = "warning"
    alerts.append(
      {
        "title": f"{result['name']} 证书即将过期",
        "level": "warning",
        "message": f"{host} 的 TLS 证书剩余 {remaining_days} 天，请检查自动续期任务。",
      }
    )
  else:
    result["status"] = "healthy"

  return result, alerts


def collect_proxies(config):
  proxies = []
  certificates = []
  alerts = []

  for item in config.get("proxies", []):
    code, latency_ms, error = check_url(item["url"])
    proxy_status = map_proxy_status(code, latency_ms or 0)
    cert_data, cert_alerts = check_certificate(item["url"], item)
    combined_status = merge_statuses(proxy_status, cert_data["status"])
    now_text = datetime.now(TZ).strftime("%H:%M:%S")
    linked_services = ", ".join(item.get("dockerServices", [])) or "--"

    metrics = {
      "HTTP 检测": format_http_state(code),
      "最近延迟": f"{latency_ms} ms" if latency_ms is not None else "--",
      "容器关联": linked_services,
      "证书状态": cert_data["status"],
      "上次检查": now_text,
    }

    proxies.append(
      {
        "name": item["name"],
        "host": item.get("host", item["url"]),
        "target": item["url"],
        "status": combined_status,
        "description": item.get("description", ""),
        "metrics": metrics,
      }
    )
    certificates.append(cert_data)
    alerts.extend(cert_alerts)

    if proxy_status != "healthy":
      alert_message = error or f"{item['url']} 返回状态码 {code}"
      if proxy_status == "warning" and code and latency_ms is not None and 200 <= code < 400:
        alert_message = f"{item['url']} 响应偏慢，当前延迟 {latency_ms} ms"
      alerts.append(
        {
          "title": f"{item['name']} 代理状态异常",
          "level": "warning" if proxy_status == "warning" else "error",
          "message": alert_message,
        }
      )

  overall = "healthy"
  if any(proxy["status"] == "error" for proxy in proxies):
    overall = "error"
  elif any(proxy["status"] in {"warning", "restarting"} for proxy in proxies):
    overall = "warning"

  summary_map = {
    "healthy": "代理站点整体正常",
    "warning": "部分代理站点需要关注",
    "error": "存在不可用代理站点",
  }
  return (
    {"overallStatus": overall, "summary": summary_map[overall], "proxies": proxies},
    {"items": certificates},
    alerts,
  )


def normalize_container_status(state, health):
  state = (state or "unknown").lower()
  health = (health or "").lower()

  if state == "running" and health in {"healthy", ""}:
    return "running"
  if state == "running" and health in {"starting", "unhealthy"}:
    return "restarting" if health == "starting" else "warning"
  if "restart" in state:
    return "restarting"
  if state in {"exited", "dead", "created"}:
    return "stopped"
  return state


def collect_docker(config):
  output, error = run_command(["docker", "ps", "-a", "--format", "{{json .}}"])
  service_config = {item["name"]: item for item in config.get("dockerServices", [])}
  services = []
  alerts = []

  if error:
    return (
      {
        "overallStatus": "error",
        "summary": "Docker 信息读取失败",
        "services": [],
      },
      [
        {
          "title": "Docker 命令执行失败",
          "level": "error",
          "message": error,
        }
      ],
    )

  known_names = set(service_config.keys())
  rows = [json.loads(line) for line in output.splitlines() if line.strip()]

  for row in rows:
    name = row.get("Names") or "unknown"
    if known_names and name not in known_names:
      continue

    state = row.get("State", "unknown")
    status_text = row.get("Status", "")
    health = ""
    if "(" in status_text and ")" in status_text:
      health = status_text.split("(")[-1].rstrip(")")
    status = normalize_container_status(state, health)
    meta = service_config.get(name, {})
    linked_sites = meta.get("sites", [])
    link_text = ", ".join(site.get("url", "--") for site in linked_sites) or "--"
    proxy_names = ", ".join(site.get("proxy", "--") for site in linked_sites if site.get("proxy")) or "--"

    services.append(
      {
        "name": name,
        "image": row.get("Image", "--"),
        "runtime": status_text or "--",
        "status": status,
        "description": meta.get("description", ""),
        "links": linked_sites,
        "metrics": {
          "端口": row.get("Ports", "--") or "--",
          "重启状态": state,
          "健康检查": health or "unknown",
          "网页地址": link_text,
          "关联代理": proxy_names,
        },
      }
    )

    if status != "running":
      alerts.append(
        {
          "title": f"{name} 容器状态异常",
          "level": "warning" if status in {"warning", "restarting"} else "error",
          "message": f"{name} 当前状态为 {status_text or state}",
        }
      )

  for expected, meta in service_config.items():
    if any(service["name"] == expected for service in services):
      continue
    services.append(
      {
        "name": expected,
        "image": "--",
        "runtime": "未发现容器",
        "status": "stopped",
        "description": meta.get("description", ""),
        "links": meta.get("sites", []),
        "metrics": {
          "端口": "--",
          "重启状态": "missing",
          "健康检查": "unknown",
          "网页地址": ", ".join(site.get("url", "--") for site in meta.get("sites", [])) or "--",
          "关联代理": ", ".join(site.get("proxy", "--") for site in meta.get("sites", []) if site.get("proxy")) or "--",
        },
      }
    )
    alerts.append(
      {
        "title": f"{expected} 容器未运行",
        "level": "error",
        "message": "在 docker ps -a 中未找到该服务，请检查容器名是否正确。",
      }
    )

  overall = "healthy"
  if any(service["status"] in {"stopped", "dead", "error"} for service in services):
    overall = "error"
  elif any(service["status"] in {"warning", "restarting"} for service in services):
    overall = "warning"

  summary_map = {
    "healthy": "Docker 服务整体正常",
    "warning": "存在需要关注的容器",
    "error": "存在停止或异常容器",
  }
  return {"overallStatus": overall, "summary": summary_map[overall], "services": services}, alerts


def summarize_certificates(certificates):
  items = certificates.get("items", [])
  overall = "healthy"
  if any(item["status"] == "error" for item in items):
    overall = "error"
  elif any(item["status"] == "warning" for item in items):
    overall = "warning"
  elif any(item["status"] == "neutral" for item in items) and items:
    overall = "neutral"

  summary_map = {
    "healthy": "证书状态正常",
    "warning": "存在即将过期证书",
    "error": "存在异常或过期证书",
    "neutral": "部分站点未启用 HTTPS",
  }
  return {"overallStatus": overall, "summary": summary_map.get(overall, "等待数据"), "items": items}


def build_overview(proxies, docker_services, certificate_items, alerts):
  total_items = len(proxies) + len(docker_services) + len(certificate_items)
  healthy_items = sum(
    1
    for item in [*proxies, *docker_services, *certificate_items]
    if item["status"] in {"healthy", "running"}
  )
  score = round((healthy_items / total_items) * 100) if total_items else 0

  if alerts:
    message = f"当前共有 {len(alerts)} 条活跃告警，优先关注证书过期与停止中的容器。"
  else:
    message = "所有代理站点、Docker 服务与证书状态都正常。"

  return score, message


def write_status(payload):
  OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
  with OUTPUT_PATH.open("w", encoding="utf-8") as file:
    json.dump(payload, file, ensure_ascii=False, indent=2)


def main():
  user_config = load_config()
  config = merge_discovered_config(user_config)
  nginx_data, certificate_data, nginx_alerts = collect_proxies(config)
  docker_data, docker_alerts = collect_docker(config)
  certificates = summarize_certificates(certificate_data)
  alerts = nginx_alerts + docker_alerts
  if config.get("discoveryErrors", {}).get("docker") and not docker_data["services"]:
    alerts.append(
      {
        "title": "自动发现 Docker 服务失败",
        "level": "warning",
        "message": config["discoveryErrors"]["docker"],
      }
    )
  score, message = build_overview(
    nginx_data["proxies"],
    docker_data["services"],
    certificates["items"],
    alerts,
  )

  payload = {
    "generatedAt": iso_now(),
    "autoSync": {
      "enabled": True,
      "intervalSeconds": SYNC_INTERVAL,
    },
    "overview": {
      "healthScore": score,
      "message": message,
    },
    "nginx": nginx_data,
    "docker": docker_data,
    "certificates": certificates,
    "alerts": alerts,
  }

  write_status(payload)
  print(f"status synced to {OUTPUT_PATH}")


if __name__ == "__main__":
  try:
    main()
  except Exception as error:
    print(f"sync failed: {error}", file=sys.stderr)
    sys.exit(1)
