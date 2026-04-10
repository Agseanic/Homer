const DATA_URL = "./data/status.json";
const REFRESH_INTERVAL = 15000;

const statusClassMap = {
  healthy: "status-good",
  running: "status-good",
  up: "status-good",
  warning: "status-warn",
  restarting: "status-warn",
  degraded: "status-warn",
  error: "status-bad",
  down: "status-bad",
  exited: "status-bad",
  stopped: "status-bad",
  neutral: "status-neutral",
  unknown: "status-neutral",
};

const elements = {
  autoSyncState: document.querySelector("#auto-sync-state"),
  lastSync: document.querySelector("#last-sync"),
  proxyTotal: document.querySelector("#proxy-total"),
  dockerTotal: document.querySelector("#docker-total"),
  alertTotal: document.querySelector("#alert-total"),
  healthScore: document.querySelector("#health-score"),
  healthText: document.querySelector("#health-text"),
  proxyStatusText: document.querySelector("#proxy-status-text"),
  dockerStatusText: document.querySelector("#docker-status-text"),
  alertStatusText: document.querySelector("#alert-status-text"),
  proxyList: document.querySelector("#proxy-list"),
  dockerList: document.querySelector("#docker-list"),
  alertList: document.querySelector("#alert-list"),
  proxyBadge: document.querySelector("#proxy-badge"),
  dockerBadge: document.querySelector("#docker-badge"),
  recommendationCount: document.querySelector("#recommendation-count"),
  refreshButton: document.querySelector("#manual-refresh"),
  serviceRowTemplate: document.querySelector("#service-row-template"),
  alertTemplate: document.querySelector("#alert-template"),
  detailModal: document.querySelector("#detail-modal"),
  detailBackdrop: document.querySelector("#detail-backdrop"),
  detailClose: document.querySelector("#detail-close"),
  detailTitle: document.querySelector("#detail-title"),
  detailBody: document.querySelector("#detail-body"),
};

function safeSetText(element, value) {
  if (element) element.textContent = value;
}

function getStatusClass(status) {
  return statusClassMap[(status || "unknown").toLowerCase()] || "status-neutral";
}

function formatDate(input) {
  if (!input) return "--";
  const date = new Date(input);
  if (Number.isNaN(date.getTime())) return input;
  const formatter = new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
  const parts = Object.fromEntries(formatter.formatToParts(date).map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

function formatMetricValue(label, value) {
  if (value == null || value === "") return "--";
  if (typeof value !== "string") return String(value);
  const looksLikeDate =
    label.includes("时间") ||
    label.includes("过期") ||
    label.includes("续期") ||
    /^\d{4}-\d{2}-\d{2}T/.test(value);
  return looksLikeDate ? formatDate(value) : value;
}

function setBadge(element, text, status) {
  if (!element) return;
  element.className = `status-badge ${getStatusClass(status)}`;
  element.textContent = text;
}

function createMetricItem(label, value) {
  const wrapper = document.createElement("div");
  const term = document.createElement("dt");
  const desc = document.createElement("dd");
  term.textContent = label;
  desc.textContent = formatMetricValue(label, value);
  wrapper.append(term, desc);
  return wrapper;
}

function createRow(item) {
  const row = elements.serviceRowTemplate.content.firstElementChild.cloneNode(true);
  const titleNode = row.querySelector(".service-title");
  const link = row.querySelector(".service-primary-link");
  const description = row.querySelector(".service-description");
  const badge = row.querySelector(".status-badge");
  const metrics = row.querySelector(".service-metrics");
  const actions = row.querySelector(".service-actions");

  safeSetText(titleNode, item.name);
  if (item.primaryLink?.url && link) {
    link.href = item.primaryLink.url;
    safeSetText(link, item.primaryLink.label || item.primaryLink.url);
  } else if (link) {
    link.remove();
  }

  if (item.description) {
    safeSetText(description, item.description);
  } else if (description) {
    description.remove();
  }

  setBadge(badge, item.statusText || item.status || "unknown", item.status);
  if (metrics) {
    Object.entries(item.metrics || {}).forEach(([label, value]) => {
      metrics.append(createMetricItem(label, value));
    });
  }

  if (item.action && actions) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "service-action";
    button.textContent = item.action.label;
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      item.action.onClick();
    });
    actions.append(button);
  } else if (actions) {
    actions.remove();
  }

  return row;
}

function renderRows(container, items) {
  if (!container || !elements.serviceRowTemplate) return;
  container.innerHTML = "";
  if (!items.length) {
    container.className = "row-list empty-state";
    container.textContent = "暂无数据，等待下一次同步。";
    return;
  }

  container.className = "row-list";
  const fragment = document.createDocumentFragment();
  items.forEach((item) => fragment.append(createRow(item)));
  container.append(fragment);
}

function renderAlerts(alerts) {
  if (!elements.alertList || !elements.alertTemplate) return;
  elements.alertList.innerHTML = "";
  if (!alerts.length) {
    elements.alertList.className = "alert-list empty-state";
    elements.alertList.textContent = "当前没有活跃告警，整体运行平稳。";
    return;
  }

  elements.alertList.className = "alert-list";
  const fragment = document.createDocumentFragment();
  alerts.forEach((alert) => {
    const node = elements.alertTemplate.content.firstElementChild.cloneNode(true);
    safeSetText(node.querySelector(".alert-title"), alert.title);
    safeSetText(node.querySelector(".alert-message"), alert.message);
    setBadge(node.querySelector(".status-badge"), alert.level, alert.level);
    fragment.append(node);
  });
  elements.alertList.append(fragment);
}

function buildCertificateMap(certificates) {
  const map = new Map();
  certificates.forEach((item) => {
    if (item.sourceUrl) map.set(item.sourceUrl, item);
    if (item.domain) map.set(item.domain, item);
  });
  return map;
}

function openDetailModal(title, rows) {
  if (!elements.detailModal || !elements.detailBody) return;
  safeSetText(elements.detailTitle, title);
  elements.detailBody.innerHTML = "";
  if (!rows.length) {
    elements.detailBody.textContent = "没有找到关联容器。";
  } else {
    const fragment = document.createDocumentFragment();
    rows.forEach((row) => fragment.append(createRow(row)));
    elements.detailBody.append(fragment);
  }
  elements.detailModal.classList.remove("hidden");
  elements.detailModal.setAttribute("aria-hidden", "false");
}

function closeDetailModal() {
  if (!elements.detailModal) return;
  elements.detailModal.classList.add("hidden");
  elements.detailModal.setAttribute("aria-hidden", "true");
}

function buildDockerDetailRows(containers) {
  return containers.map((item) => ({
    name: item.name,
    primaryLink: item.links?.[0]?.url ? { label: item.links[0].url, url: item.links[0].url } : null,
    description: item.description || "",
    status: item.status,
    statusText: item.status,
    metrics: {
      "镜像": item.image || "--",
      "运行状态": item.runtime || "--",
      "端口": item.metrics?.["端口"] || "--",
      "健康检查": item.metrics?.["健康检查"] || "--",
      "关联代理": item.metrics?.["关联代理"] || "--",
      "网页地址": item.metrics?.["网页地址"] || "--",
    },
  }));
}

function buildProxyRows(proxies, containers, certificateMap) {
  const containerMap = new Map(containers.map((item) => [item.name, item]));
  return proxies.map((proxy) => {
    const certificate = certificateMap.get(proxy.target) || certificateMap.get(proxy.host);
    const certMetrics = certificate?.metrics || {};
    const linkedNames = (proxy.metrics?.["容器关联"] || "")
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean)
      .filter((item) => item !== "--");
    const linkedContainers = linkedNames.map((name) => containerMap.get(name)).filter(Boolean);

    return {
      name: proxy.host || proxy.name,
      primaryLink: proxy.target ? { label: proxy.target, url: proxy.target } : null,
      description: proxy.description || "",
      status: proxy.status,
      statusText: proxy.status,
      metrics: {
        "HTTP 检测": proxy.metrics?.["HTTP 检测"] || "--",
        "最近延迟": proxy.metrics?.["最近延迟"] || "--",
        "关联容器": linkedNames.join(", ") || "无",
        "证书状态": certificate ? certificate.status : "未配置证书",
        "证书过期": certMetrics["过期时间"] || "未配置证书",
        "剩余天数": certMetrics["剩余天数"] || "--",
        "自动更新": certMetrics["自动更新时间"] || "--",
        "检查时间": certMetrics["检查时间"] || proxy.metrics?.["上次检查"] || "--",
      },
      action: linkedContainers.length
        ? {
            label: "关联容器",
            onClick: () => openDetailModal(`${proxy.host || proxy.name} 关联容器`, buildDockerDetailRows(linkedContainers)),
          }
        : null,
    };
  });
}

function buildUnlinkedDockerRows(containers) {
  return containers
    .filter((item) => {
      const linkedProxy = item.metrics?.["关联代理"];
      const linkedSite = item.metrics?.["网页地址"];
      return !linkedProxy || linkedProxy === "--" || !linkedSite || linkedSite === "--";
    })
    .map((item) => ({
      name: item.name,
      primaryLink: item.links?.[0]?.url ? { label: item.links[0].url, url: item.links[0].url } : null,
      description: item.description || "",
      status: item.status,
      statusText: item.status,
      metrics: {
        "镜像": item.image || "--",
        "运行状态": item.runtime || "--",
        "端口": item.metrics?.["端口"] || "--",
        "健康检查": item.metrics?.["健康检查"] || "--",
        "关联代理": item.metrics?.["关联代理"] || "--",
        "网页地址": item.metrics?.["网页地址"] || "--",
      },
    }));
}

function renderDashboard(data) {
  const proxies = data.nginx?.proxies || [];
  const containers = data.docker?.services || [];
  const certificates = data.certificates?.items || [];
  const alerts = data.alerts || [];
  const certificateMap = buildCertificateMap(certificates);
  const proxyRows = buildProxyRows(proxies, containers, certificateMap);
  const dockerRows = buildUnlinkedDockerRows(containers);
  const totalCount = proxies.length + containers.length;
  const healthyCount = [...proxies, ...containers].filter((item) =>
    ["healthy", "running", "up"].includes((item.status || "").toLowerCase())
  ).length;
  const healthScore = totalCount ? Math.round((healthyCount / totalCount) * 100) : 0;

  safeSetText(elements.autoSyncState, data.autoSync?.enabled ? "已启用" : "未启用");
  safeSetText(elements.lastSync, formatDate(data.generatedAt));
  safeSetText(elements.proxyTotal, String(proxies.length));
  safeSetText(elements.dockerTotal, String(dockerRows.length));
  safeSetText(elements.alertTotal, String(alerts.length));
  safeSetText(elements.healthScore, `${healthScore}%`);
  safeSetText(elements.healthText, data.overview?.message || "已根据最新同步结果更新");
  safeSetText(elements.proxyStatusText, `${proxies.filter((item) => item.status === "healthy").length} 个正常`);
  safeSetText(elements.dockerStatusText, `${dockerRows.length} 个未关联`);
  safeSetText(elements.alertStatusText, alerts.length ? "需要关注" : "暂无异常");

  setBadge(elements.proxyBadge, data.nginx?.summary || "等待数据", data.nginx?.overallStatus || "neutral");
  setBadge(elements.dockerBadge, dockerRows.length ? "存在未关联容器" : "已隐藏已关联容器", dockerRows.length ? "warning" : "healthy");
  setBadge(
    elements.recommendationCount,
    `${alerts.length} 条建议`,
    alerts.length ? alerts[0].level : "neutral"
  );

  renderRows(elements.proxyList, proxyRows);
  renderRows(elements.dockerList, dockerRows);
  renderAlerts(alerts);
}

async function loadStatus() {
  try {
    if (elements.refreshButton) elements.refreshButton.disabled = true;
    const response = await fetch(`${DATA_URL}?t=${Date.now()}`, { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    renderDashboard(data);
  } catch (error) {
    safeSetText(elements.autoSyncState, "读取失败");
    safeSetText(elements.lastSync, "无法获取");
    safeSetText(elements.healthText, `状态文件读取失败：${error.message}`);
  } finally {
    if (elements.refreshButton) elements.refreshButton.disabled = false;
  }
}

if (elements.refreshButton) elements.refreshButton.addEventListener("click", loadStatus);
if (elements.detailClose) elements.detailClose.addEventListener("click", closeDetailModal);
if (elements.detailBackdrop) elements.detailBackdrop.addEventListener("click", closeDetailModal);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeDetailModal();
});

loadStatus();
window.setInterval(loadStatus, REFRESH_INTERVAL);
