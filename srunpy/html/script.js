"use strict";

const {
  AUTO_INTERFACE_TOKEN,
  formatTraffic,
  formatRate,
  formatDuration,
  interfaceFromToken,
} = window.SRunPyUtils;

const applicationState = {
  config: null,
  connection: null,
  busy: false,
  connectionPollTimerId: null,
  connectionPollInFlight: false,
  probeResults: [],
  traffic: {
    snapshot: null,
    points: [],
    selectedRange: "recent",
    pollTimerId: null,
    pollInFlight: false,
  },
};

const elements = {};

function cacheElements() {
  const elementIds = [
    "version-label",
    "live-badge",
    "live-badge-text",
    "refresh-button",
    "update-banner",
    "settings-button",
    "status-panel",
    "status-title",
    "status-message",
    "last-updated-label",
    "retry-connection-button",
    "interface-select",
    "account-title",
    "credential-badge",
    "security-mode-label",
    "login-form",
    "username-input",
    "password-input",
    "password-visibility",
    "form-message",
    "primary-action",
    "metric-username",
    "metric-ip",
    "metric-traffic",
    "metric-balance",
    "traffic-panel",
    "traffic-interface-label",
    "traffic-range-controls",
    "traffic-range-recent",
    "traffic-range-hour",
    "traffic-range-five-hours",
    "traffic-range-twelve-hours",
    "traffic-range-day",
    "traffic-range-week",
    "traffic-download-rate",
    "traffic-upload-rate",
    "traffic-peak-rate",
    "traffic-peak-detail",
    "traffic-duration",
    "traffic-chart-region",
    "traffic-chart",
    "traffic-status",
    "auto-login-toggle",
    "auto-start-toggle",
    "self-service-button",
    "gateway-label",
    "settings-dialog",
    "settings-form",
    "close-settings-button",
    "cancel-settings-button",
    "save-settings-button",
    "gateway-input",
    "self-service-input",
    "probe-button",
    "interface-options",
    "probe-message",
    "reconnect-interval-input",
    "unverified-tls-toggle",
    "insecure-http-toggle",
    "settings-message",
    "traffic-sampling-toggle",
    "traffic-history-toggle",
    "traffic-retention-input",
    "clear-traffic-history-button",
  ];
  elementIds.forEach((elementId) => {
    elements[elementId] = document.getElementById(elementId);
  });
}

async function waitForBackend() {
  while (!(window.pywebview && window.pywebview.api)) {
    await new Promise((resolve) => window.setTimeout(resolve, 80));
  }
  return window.pywebview.api;
}

function activeInterfaceValue() {
  const activeIp = applicationState.config ? applicationState.config.active_ip : null;
  return activeIp === null || typeof activeIp === "undefined"
    ? AUTO_INTERFACE_TOKEN
    : String(activeIp);
}

function setMessage(element, message, state = "") {
  element.textContent = message || "";
  if (state) {
    element.dataset.state = state;
  } else {
    delete element.dataset.state;
  }
}

function setBusy(isBusy, message = "") {
  applicationState.busy = isBusy;
  elements["primary-action"].disabled = isBusy;
  elements["refresh-button"].disabled = isBusy;
  elements["interface-select"].disabled = isBusy;
  elements["retry-connection-button"].disabled = isBusy;
  if (message) {
    setMessage(elements["form-message"], message);
  }
}

function renderInterfaceSelector() {
  const select = elements["interface-select"];
  select.replaceChildren();
  const selectedIps = Array.isArray(applicationState.config.selected_ips)
    ? applicationState.config.selected_ips
    : [null];

  selectedIps.forEach((interfaceIp) => {
    const option = document.createElement("option");
    option.value = interfaceIp === null ? AUTO_INTERFACE_TOKEN : String(interfaceIp);
    option.textContent = interfaceIp === null ? "自动选择" : String(interfaceIp);
    select.appendChild(option);
  });

  if (!select.options.length) {
    const option = document.createElement("option");
    option.value = AUTO_INTERFACE_TOKEN;
    option.textContent = "自动选择";
    select.appendChild(option);
  }
  select.value = activeInterfaceValue();
}

function renderConfig() {
  const config = applicationState.config;
  elements["version-label"].textContent = `Windows 客户端 v${config.version}`;
  elements["username-input"].value = config.username || "";
  elements["credential-badge"].textContent = config.has_password ? "凭据已安全保存" : "未保存凭据";
  elements["credential-badge"].dataset.active = String(Boolean(config.has_password));
  elements["auto-login-toggle"].checked = Boolean(config.auto_login);
  elements["auto-start-toggle"].checked = Boolean(config.start_with_windows);
  elements["update-banner"].hidden = !config.update_available;
  elements["gateway-label"].textContent = `网关：${config.gateway}`;
  if (config.allow_insecure_http) {
    elements["security-mode-label"].textContent = "已启用明文 HTTP 兼容模式";
  } else if (config.allow_unverified_tls) {
    elements["security-mode-label"].textContent = "已允许未经验证的 HTTPS 证书";
  } else {
    elements["security-mode-label"].textContent = "使用经过证书验证的 HTTPS";
  }
  renderInterfaceSelector();
}

function renderConnection() {
  const connection = applicationState.connection;
  const statusPanel = elements["status-panel"];
  const connectionData = connection && connection.data ? connection.data : {};

  if (!connection) {
    statusPanel.dataset.state = "loading";
    elements["live-badge"].dataset.state = "loading";
    elements["live-badge-text"].textContent = "检查中";
    elements["status-title"].textContent = "正在检查网络";
    elements["status-message"].textContent = "正在连接校园网网关...";
  } else if (connection.online) {
    statusPanel.dataset.state = "online";
    elements["live-badge"].dataset.state = "online";
    elements["live-badge-text"].textContent = "在线";
    elements["status-title"].textContent = "校园网已连接";
    elements["status-message"].textContent = "当前线路认证正常";
  } else if (connection.available) {
    statusPanel.dataset.state = "offline";
    elements["live-badge"].dataset.state = "offline";
    elements["live-badge-text"].textContent = "待登录";
    elements["status-title"].textContent = "等待登录";
    elements["status-message"].textContent = "网关可访问，登录后即可使用校园网";
  } else {
    statusPanel.dataset.state = "error";
    elements["live-badge"].dataset.state = "error";
    elements["live-badge-text"].textContent = "不可用";
    elements["status-title"].textContent = "网关不可用";
    elements["status-message"].textContent = connection.message || "请检查网络接口或网关设置";
  }

  if (connection) {
    elements["last-updated-label"].textContent = new Date().toLocaleTimeString("zh-CN", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  }

  const footerDot = document.querySelector(".footer-dot");
  if (footerDot) {
    footerDot.style.background = connection && connection.online ? "var(--accent)" : "var(--muted-foreground)";
  }

  const isOnline = Boolean(connection && connection.online);
  elements["retry-connection-button"].hidden = !connection || isOnline;
  elements["account-title"].textContent = isOnline ? "当前已登录" : "账号登录";
  elements["primary-action"].textContent = isOnline ? "注销当前线路" : "登录校园网";
  elements["username-input"].disabled = isOnline;
  elements["password-input"].disabled = isOnline;
  elements["password-visibility"].disabled = isOnline;

  elements["metric-username"].textContent = connectionData.username || "--";
  elements["metric-ip"].textContent = connectionData.online_ip || "--";
  elements["metric-traffic"].textContent = formatTraffic(connectionData.account_total_bytes);
  elements["metric-balance"].textContent = connectionData.balance || "--";
}

function renderTrafficSnapshot() {
  const snapshot = applicationState.traffic.snapshot || {};
  elements["traffic-download-rate"].textContent = formatRate(snapshot.download_bytes_per_second);
  elements["traffic-upload-rate"].textContent = formatRate(snapshot.upload_bytes_per_second);
  elements["traffic-peak-rate"].textContent = formatRate(
    Math.max(
      Number(snapshot.peak_download_bytes_per_second) || 0,
      Number(snapshot.peak_upload_bytes_per_second) || 0,
    ),
  );
  elements["traffic-peak-detail"].textContent =
    `↓ ${formatRate(snapshot.peak_download_bytes_per_second)} / ` +
    `↑ ${formatRate(snapshot.peak_upload_bytes_per_second)}`;
  elements["traffic-duration"].textContent = formatDuration(snapshot.monitoring_duration_seconds);
  elements["traffic-interface-label"].textContent = snapshot.interface_name
    ? `${snapshot.interface_name} · ${snapshot.interface_ip || "IP 未知"}`
    : "尚未识别活动网卡";
  elements["traffic-status"].textContent = snapshot.available
    ? "实时速度来自 Windows 活动网卡；历史保存原始分钟平均值与峰值。"
    : snapshot.message || "实时流量暂不可用";
}

function drawTrafficChart() {
  const canvas = elements["traffic-chart"];
  const context = canvas.getContext("2d");
  if (!context) {
    return;
  }
  const bounds = canvas.getBoundingClientRect();
  if (bounds.width <= 0 || bounds.height <= 0) {
    return;
  }
  const pixelRatio = window.devicePixelRatio || 1;
  canvas.width = Math.round(bounds.width * pixelRatio);
  canvas.height = Math.round(bounds.height * pixelRatio);
  context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
  context.clearRect(0, 0, bounds.width, bounds.height);

  const styles = getComputedStyle(document.documentElement);
  const chartColors = {
    grid: styles.getPropertyValue("--border").trim(),
    text: styles.getPropertyValue("--muted-foreground").trim(),
    download: styles.getPropertyValue("--traffic-download").trim(),
    upload: styles.getPropertyValue("--traffic-upload").trim(),
  };
  const chartPadding = { top: 12, right: 12, bottom: 34, left: 54 };
  const chartWidth = Math.max(1, bounds.width - chartPadding.left - chartPadding.right);
  const chartHeight = Math.max(1, bounds.height - chartPadding.top - chartPadding.bottom);
  const points = applicationState.traffic.points;
  const finiteRates = points.flatMap((point) => [
    point.download_bytes_per_second,
    point.upload_bytes_per_second,
  ]).filter((value) => value !== null && typeof value !== "undefined")
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value) && value >= 0);
  const maximumRate = Math.max(1, ...finiteRates);

  context.strokeStyle = chartColors.grid;
  context.fillStyle = chartColors.text;
  context.font = '10px "MiSans", sans-serif';
  context.lineWidth = 1;
  for (let gridIndex = 0; gridIndex <= 4; gridIndex += 1) {
    const gridY = chartPadding.top + (chartHeight * gridIndex) / 4;
    context.beginPath();
    context.moveTo(chartPadding.left, gridY);
    context.lineTo(chartPadding.left + chartWidth, gridY);
    context.stroke();
    const gridRate = maximumRate * (1 - gridIndex / 4);
    context.fillText(formatRate(gridRate), 2, gridY + 3);
  }

  const formatAxisTime = (timestamp) => {
    const date = new Date(Number(timestamp) * 1000);
    if (Number.isNaN(date.getTime())) {
      return "--";
    }
    if (applicationState.traffic.selectedRange === "7d") {
      return `${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")}`;
    }
    const timeLabel = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
    if (applicationState.traffic.selectedRange === "recent") {
      return `${timeLabel}:${String(date.getSeconds()).padStart(2, "0")}`;
    }
    return timeLabel;
  };

  const tickIndices = new Set();
  if (points.length > 0) {
    const tickCount = Math.min(5, points.length);
    for (let tickIndex = 0; tickIndex < tickCount; tickIndex += 1) {
      tickIndices.add(Math.round((points.length - 1) * tickIndex / Math.max(1, tickCount - 1)));
    }
  }
  context.textBaseline = "top";
  Array.from(tickIndices).forEach((pointIndex, labelIndex, labels) => {
    const pointX = chartPadding.left + chartWidth * (
      points.length <= 1 ? 1 : pointIndex / (points.length - 1)
    );
    context.textAlign = labelIndex === 0 ? "left" : labelIndex === labels.length - 1 ? "right" : "center";
    context.fillText(
      formatAxisTime(points[pointIndex].timestamp),
      pointX,
      chartPadding.top + chartHeight + 9,
    );
  });
  context.textAlign = "left";
  context.textBaseline = "alphabetic";

  const traceSmoothSegment = (segment) => {
    context.beginPath();
    context.moveTo(segment[0].x, segment[0].y);
    if (segment.length === 2) {
      context.lineTo(segment[1].x, segment[1].y);
      return;
    }
    for (let pointIndex = 1; pointIndex < segment.length - 1; pointIndex += 1) {
      const currentPoint = segment[pointIndex];
      const nextPoint = segment[pointIndex + 1];
      const midpointX = (currentPoint.x + nextPoint.x) / 2;
      const midpointY = (currentPoint.y + nextPoint.y) / 2;
      context.quadraticCurveTo(currentPoint.x, currentPoint.y, midpointX, midpointY);
    }
    const penultimatePoint = segment[segment.length - 2];
    const finalPoint = segment[segment.length - 1];
    context.quadraticCurveTo(
      penultimatePoint.x,
      penultimatePoint.y,
      finalPoint.x,
      finalPoint.y,
    );
  };

  const drawSeries = (fieldName, color, dashed, fillArea = false) => {
    context.strokeStyle = color;
    context.lineWidth = 2.25;
    context.lineJoin = "round";
    context.lineCap = "round";
    context.setLineDash(dashed ? [6, 4] : []);
    const segments = [];
    let currentSegment = [];
    points.forEach((point, pointIndex) => {
      const rawRate = point[fieldName];
      const rate = Number(rawRate);
      if (point.gap || rawRate === null || typeof rawRate === "undefined" || !Number.isFinite(rate) || rate < 0) {
        if (currentSegment.length > 0) {
          segments.push(currentSegment);
          currentSegment = [];
        }
        return;
      }
      const pointX = chartPadding.left + chartWidth * (points.length <= 1 ? 1 : pointIndex / (points.length - 1));
      const pointY = chartPadding.top + chartHeight * (1 - rate / maximumRate);
      currentSegment.push({ x: pointX, y: pointY });
    });
    if (currentSegment.length > 0) {
      segments.push(currentSegment);
    }

    segments.forEach((segment) => {
      if (fillArea && segment.length > 1) {
        context.save();
        traceSmoothSegment(segment);
        context.lineTo(segment[segment.length - 1].x, chartPadding.top + chartHeight);
        context.lineTo(segment[0].x, chartPadding.top + chartHeight);
        context.closePath();
        context.globalAlpha = 0.09;
        context.fillStyle = color;
        context.fill();
        context.restore();
      }
      if (segment.length === 1) {
        context.beginPath();
        context.arc(segment[0].x, segment[0].y, 2.25, 0, Math.PI * 2);
        context.fillStyle = color;
        context.fill();
      } else {
        traceSmoothSegment(segment);
        context.stroke();
      }
    });
  };
  drawSeries("download_bytes_per_second", chartColors.download, false, true);
  drawSeries("upload_bytes_per_second", chartColors.upload, true);
  context.setLineDash([]);
}

async function refreshTrafficHistory() {
  const backend = await waitForBackend();
  const result = await backend.get_traffic_history(applicationState.traffic.selectedRange);
  applicationState.traffic.points = result.ok && Array.isArray(result.points) ? result.points : [];
  drawTrafficChart();
}

function scheduleTrafficPoll(delayMilliseconds = 1000) {
  if (applicationState.traffic.pollTimerId !== null) {
    window.clearTimeout(applicationState.traffic.pollTimerId);
  }
  if (document.hidden || !applicationState.config.traffic_sampling_enabled) {
    applicationState.traffic.pollTimerId = null;
    return;
  }
  applicationState.traffic.pollTimerId = window.setTimeout(pollTrafficSnapshot, delayMilliseconds);
}

async function pollTrafficSnapshot() {
  if (applicationState.traffic.pollInFlight || document.hidden) {
    scheduleTrafficPoll();
    return;
  }
  applicationState.traffic.pollInFlight = true;
  try {
    const backend = await waitForBackend();
    applicationState.traffic.snapshot = await backend.get_traffic_snapshot();
    renderTrafficSnapshot();
    if (applicationState.traffic.selectedRange === "recent") {
      await refreshTrafficHistory();
    }
  } catch (error) {
    elements["traffic-status"].textContent = `流量采样失败：${error}`;
  } finally {
    applicationState.traffic.pollInFlight = false;
    scheduleTrafficPoll();
  }
}

async function selectTrafficRange(event) {
  const selectedRange = event.currentTarget.dataset.range;
  if (!selectedRange) {
    return;
  }
  applicationState.traffic.selectedRange = selectedRange;
  elements["traffic-range-controls"].querySelectorAll("button[data-range]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.range === selectedRange));
  });
  await refreshTrafficHistory();
}

async function loadApplication() {
  const backend = await waitForBackend();
  try {
    applicationState.config = await backend.get_app_state();
    renderConfig();
    await refreshConnection();
    await pollTrafficSnapshot();
  } catch (error) {
    applicationState.connection = {
      available: false,
      online: false,
      data: {},
      message: String(error),
    };
    renderConnection();
  }
}

async function refreshConnection() {
  const backend = await waitForBackend();
  applicationState.connection = null;
  renderConnection();
  applicationState.connection = await backend.get_connection_status(
    interfaceFromToken(activeInterfaceValue()),
  );
  renderConnection();
  scheduleConnectionPoll();
}

function scheduleConnectionPoll() {
  if (applicationState.connectionPollTimerId !== null) {
    window.clearTimeout(applicationState.connectionPollTimerId);
    applicationState.connectionPollTimerId = null;
  }
  if (
    document.hidden ||
    !applicationState.connection ||
    applicationState.connection.online
  ) {
    return;
  }
  applicationState.connectionPollTimerId = window.setTimeout(
    pollConnectionStatus,
    12000,
  );
}

async function pollConnectionStatus() {
  applicationState.connectionPollTimerId = null;
  if (document.hidden || applicationState.connectionPollInFlight) {
    return;
  }
  applicationState.connectionPollInFlight = true;
  try {
    await refreshConnection();
  } catch (error) {
    applicationState.connection = {
      available: false,
      online: false,
      data: {},
      message: String(error),
    };
    renderConnection();
  } finally {
    applicationState.connectionPollInFlight = false;
  }
}

async function retryConnection() {
  if (applicationState.busy) {
    return;
  }
  const backend = await waitForBackend();
  setBusy(true, "正在重试连接...");
  try {
    const result = await backend.perform_login(
      elements["username-input"].value,
      elements["password-input"].value,
      interfaceFromToken(activeInterfaceValue()),
    );
    setMessage(elements["form-message"], result.message, result.ok ? "success" : "error");
    if (result.ok) {
      elements["password-input"].value = "";
      applicationState.config = await backend.get_app_state();
      renderConfig();
      await refreshConnection();
    }
  } catch (error) {
    setMessage(elements["form-message"], String(error), "error");
  } finally {
    setBusy(false);
  }
}

async function handlePrimaryAction(event) {
  event.preventDefault();
  if (applicationState.busy) {
    return;
  }
  const backend = await waitForBackend();
  const isOnline = Boolean(applicationState.connection && applicationState.connection.online);
  setBusy(true, isOnline ? "正在注销..." : "正在登录...");

  try {
    let result;
    if (isOnline) {
      result = await backend.perform_logout(interfaceFromToken(activeInterfaceValue()));
    } else {
      result = await backend.perform_login(
        elements["username-input"].value,
        elements["password-input"].value,
        interfaceFromToken(activeInterfaceValue()),
      );
    }
    setMessage(elements["form-message"], result.message, result.ok ? "success" : "error");
    if (result.ok) {
      elements["password-input"].value = "";
      applicationState.config = await backend.get_app_state();
      renderConfig();
      await refreshConnection();
    }
  } catch (error) {
    setMessage(elements["form-message"], String(error), "error");
  } finally {
    setBusy(false);
  }
}

async function handleInterfaceChange() {
  const backend = await waitForBackend();
  const selectedIp = interfaceFromToken(elements["interface-select"].value);
  const changed = await backend.set_active_client_ip(selectedIp);
  if (!changed) {
    elements["interface-select"].value = activeInterfaceValue();
    setMessage(elements["form-message"], "无法切换到所选线路", "error");
    return;
  }
  applicationState.config.active_ip = selectedIp;
  await refreshConnection();
  applicationState.traffic.points = [];
  await pollTrafficSnapshot();
}

async function handleAutoLoginToggle() {
  const backend = await waitForBackend();
  elements["auto-login-toggle"].disabled = true;
  try {
    const desiredValue = elements["auto-login-toggle"].checked;
    const changed = await backend.set_auto_login(desiredValue);
    if (!changed) {
      elements["auto-login-toggle"].checked = false;
      setMessage(elements["form-message"], "请先使用正确凭据成功登录一次", "error");
    }
    applicationState.config = await backend.get_app_state();
    renderConfig();
  } catch (error) {
    elements["auto-login-toggle"].checked = !elements["auto-login-toggle"].checked;
    setMessage(elements["form-message"], `无法修改断线重连：${error}`, "error");
  } finally {
    elements["auto-login-toggle"].disabled = false;
  }
}

async function handleAutoStartToggle() {
  const backend = await waitForBackend();
  elements["auto-start-toggle"].disabled = true;
  try {
    await backend.set_start_with_windows(elements["auto-start-toggle"].checked);
    applicationState.config = await backend.get_app_state();
    renderConfig();
  } catch (error) {
    elements["auto-start-toggle"].checked = !elements["auto-start-toggle"].checked;
    setMessage(elements["form-message"], `无法修改开机启动：${error}`, "error");
  } finally {
    elements["auto-start-toggle"].disabled = false;
  }
}

function openSettings() {
  const config = applicationState.config;
  elements["gateway-input"].value = config.gateway || "";
  elements["self-service-input"].value = config.self_service || "";
  elements["reconnect-interval-input"].value = String(config.reconnect_interval || 5);
  elements["unverified-tls-toggle"].checked = Boolean(config.allow_unverified_tls);
  elements["insecure-http-toggle"].checked = Boolean(config.allow_insecure_http);
  elements["traffic-sampling-toggle"].checked = Boolean(config.traffic_sampling_enabled);
  elements["traffic-history-toggle"].checked = Boolean(config.traffic_history_enabled);
  elements["traffic-retention-input"].value = String(config.traffic_retention_days || 7);
  applicationState.probeResults = [];
  renderInterfaceOptions();
  setMessage(elements["probe-message"], "");
  setMessage(elements["settings-message"], "");
  elements["settings-dialog"].showModal();
}

function getSettingsInterfaces() {
  if (applicationState.probeResults.length) {
    return applicationState.probeResults;
  }
  const availableIps = Array.isArray(applicationState.config.available_ips)
    ? applicationState.config.available_ips
    : [];
  return [
    { ip: null, label: "自动选择", reachable: null, message: "使用系统默认路由" },
    ...availableIps.map((interfaceIp) => ({
      ip: interfaceIp,
      label: interfaceIp,
      reachable: null,
      message: "本机 IPv4 地址",
    })),
  ];
}

function renderInterfaceOptions() {
  const selectedTokens = new Set(
    (applicationState.config.selected_ips || [null]).map((interfaceIp) =>
      interfaceIp === null ? AUTO_INTERFACE_TOKEN : String(interfaceIp),
    ),
  );
  const activeToken = activeInterfaceValue();
  elements["interface-options"].replaceChildren();

  getSettingsInterfaces().forEach((interfaceInfo) => {
    const interfaceToken = interfaceInfo.ip === null ? AUTO_INTERFACE_TOKEN : String(interfaceInfo.ip);
    const row = document.createElement("div");
    row.className = "interface-option";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = interfaceToken;
    checkbox.checked = selectedTokens.has(interfaceToken);
    checkbox.dataset.role = "selected-interface";

    const description = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = interfaceInfo.label || interfaceToken;
    const detail = document.createElement("small");
    detail.textContent = interfaceInfo.message || "";
    description.append(title, document.createElement("br"), detail);

    const radioLabel = document.createElement("label");
    const radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "active-interface";
    radio.value = interfaceToken;
    radio.checked = interfaceToken === activeToken;
    radio.dataset.role = "active-interface";
    radio.addEventListener("change", () => {
      checkbox.checked = true;
    });
    radioLabel.append(radio, " 当前");
    row.append(checkbox, description, radioLabel);
    elements["interface-options"].appendChild(row);
  });
}

async function probeInterfaces() {
  const backend = await waitForBackend();
  elements["probe-button"].disabled = true;
  setMessage(elements["probe-message"], "正在检查各网络接口...");
  try {
    const result = await backend.probe_gateway_ips(
      elements["gateway-input"].value,
      elements["self-service-input"].value,
    );
    if (!result.ok) {
      setMessage(elements["probe-message"], result.error || "检查失败", "error");
      return;
    }
    applicationState.probeResults = Array.isArray(result.results) ? result.results : [];
    renderInterfaceOptions();
    setMessage(
      elements["probe-message"],
      `已检查 ${applicationState.probeResults.length} 条线路，${result.reachable_count} 条可访问`,
      result.reachable_count > 0 ? "success" : "error",
    );
  } catch (error) {
    setMessage(elements["probe-message"], `检查失败：${error}`, "error");
  } finally {
    elements["probe-button"].disabled = false;
  }
}

function collectInterfaceSettings() {
  const selectedCheckboxes = elements["interface-options"].querySelectorAll(
    'input[data-role="selected-interface"]:checked',
  );
  const selectedIps = Array.from(selectedCheckboxes).map((checkbox) =>
    interfaceFromToken(checkbox.value),
  );
  const activeRadio = elements["interface-options"].querySelector(
    'input[data-role="active-interface"]:checked',
  );
  const activeIp = activeRadio ? interfaceFromToken(activeRadio.value) : selectedIps[0] || null;
  return { selectedIps: selectedIps.length ? selectedIps : [null], activeIp };
}

async function saveSettings(event) {
  event.preventDefault();
  const backend = await waitForBackend();
  const interfaceSettings = collectInterfaceSettings();
  elements["save-settings-button"].disabled = true;
  setMessage(elements["settings-message"], "正在保存设置...");
  try {
    const result = await backend.update_preferences({
      gateway: elements["gateway-input"].value,
      self_service: elements["self-service-input"].value,
      reconnect_interval: Number(elements["reconnect-interval-input"].value),
      selected_ips: interfaceSettings.selectedIps,
      active_ip: interfaceSettings.activeIp,
      allow_unverified_tls: elements["unverified-tls-toggle"].checked,
      allow_insecure_http: elements["insecure-http-toggle"].checked,
    });
    if (!result.ok) {
      setMessage(elements["settings-message"], result.message, "error");
      return;
    }
    const trafficResult = await backend.update_traffic_preferences({
      enabled: elements["traffic-sampling-toggle"].checked,
      sample_interval: applicationState.config.traffic_sample_interval || 1,
      history_enabled: elements["traffic-history-toggle"].checked,
      retention_days: Number(elements["traffic-retention-input"].value),
    });
    if (!trafficResult.ok) {
      setMessage(elements["settings-message"], trafficResult.message, "error");
      return;
    }
    applicationState.config = await backend.get_app_state();
    renderConfig();
    elements["settings-dialog"].close();
    setMessage(elements["form-message"], result.message, "success");
    await refreshConnection();
    scheduleTrafficPoll(0);
  } catch (error) {
    setMessage(elements["settings-message"], String(error), "error");
  } finally {
    elements["save-settings-button"].disabled = false;
  }
}

function togglePasswordVisibility() {
  const isPassword = elements["password-input"].type === "password";
  elements["password-input"].type = isPassword ? "text" : "password";
  elements["password-visibility"].textContent = isPassword ? "隐藏" : "显示";
}

async function clearTrafficHistory() {
  const backend = await waitForBackend();
  elements["clear-traffic-history-button"].disabled = true;
  try {
    const result = await backend.clear_traffic_history();
    setMessage(elements["settings-message"], result.message, result.ok ? "success" : "error");
    if (result.ok) {
      applicationState.traffic.points = [];
      drawTrafficChart();
    }
  } catch (error) {
    setMessage(elements["settings-message"], String(error), "error");
  } finally {
    elements["clear-traffic-history-button"].disabled = false;
  }
}

function handleVisibilityChange() {
  if (document.hidden) {
    if (applicationState.traffic.pollTimerId !== null) {
      window.clearTimeout(applicationState.traffic.pollTimerId);
      applicationState.traffic.pollTimerId = null;
    }
    if (applicationState.connectionPollTimerId !== null) {
      window.clearTimeout(applicationState.connectionPollTimerId);
      applicationState.connectionPollTimerId = null;
    }
    return;
  }
  scheduleTrafficPoll(0);
  drawTrafficChart();
  if (!applicationState.connection || !applicationState.connection.online) {
    pollConnectionStatus();
  }
}

function bindEvents() {
  elements["login-form"].addEventListener("submit", handlePrimaryAction);
  elements["refresh-button"].addEventListener("click", refreshConnection);
  elements["retry-connection-button"].addEventListener("click", retryConnection);
  elements["update-banner"].addEventListener("click", async (event) => {
    event.preventDefault();
    const backend = await waitForBackend();
    try {
      await backend.open_releases_page();
    } catch (error) {
      window.open("https://github.com/cjdem/SRunPy-GUI/releases/latest", "_blank");
    }
  });
  elements["interface-select"].addEventListener("change", handleInterfaceChange);
  elements["auto-login-toggle"].addEventListener("change", handleAutoLoginToggle);
  elements["auto-start-toggle"].addEventListener("change", handleAutoStartToggle);
  elements["password-visibility"].addEventListener("click", togglePasswordVisibility);
  elements["settings-button"].addEventListener("click", openSettings);
  elements["close-settings-button"].addEventListener("click", () => elements["settings-dialog"].close());
  elements["cancel-settings-button"].addEventListener("click", () => elements["settings-dialog"].close());
  elements["settings-form"].addEventListener("submit", saveSettings);
  elements["probe-button"].addEventListener("click", probeInterfaces);
  elements["traffic-range-controls"].querySelectorAll("button[data-range]").forEach((button) => {
    button.addEventListener("click", selectTrafficRange);
  });
  elements["clear-traffic-history-button"].addEventListener("click", clearTrafficHistory);
  document.addEventListener("visibilitychange", handleVisibilityChange);
  window.addEventListener("resize", drawTrafficChart);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", drawTrafficChart);
  elements["self-service-button"].addEventListener("click", async () => {
    const backend = await waitForBackend();
    await backend.start_self_service(interfaceFromToken(activeInterfaceValue()));
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  cacheElements();
  bindEvents();
  await loadApplication();
});
