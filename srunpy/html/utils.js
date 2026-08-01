"use strict";

// Shared pure helpers used by the desktop dashboard. Kept DOM-free so the
// formatting and token logic can be unit-tested with Node.js.
(function attachUtils(global) {
  const AUTO_INTERFACE_TOKEN = "__auto__";

  function formatTraffic(rawBytes) {
    if (rawBytes === null || typeof rawBytes === "undefined" || rawBytes === "") {
      return "--";
    }
    const byteCount = Number(rawBytes);
    if (!Number.isFinite(byteCount) || byteCount < 0) {
      return "--";
    }
    if (byteCount >= 1024 ** 3) {
      return `${(byteCount / 1024 ** 3).toFixed(2)} GB`;
    }
    return `${(byteCount / 1024 ** 2).toFixed(2)} MB`;
  }

  function formatRate(rawBytesPerSecond) {
    if (
      rawBytesPerSecond === null ||
      typeof rawBytesPerSecond === "undefined" ||
      rawBytesPerSecond === ""
    ) {
      return "--";
    }
    const rate = Number(rawBytesPerSecond);
    if (!Number.isFinite(rate) || rate < 0) {
      return "--";
    }
    const units = ["B/s", "KB/s", "MB/s", "GB/s"];
    let scaledRate = rate;
    let unitIndex = 0;
    while (scaledRate >= 1024 && unitIndex < units.length - 1) {
      scaledRate /= 1024;
      unitIndex += 1;
    }
    const decimalPlaces = scaledRate >= 100 || unitIndex === 0 ? 0 : scaledRate >= 10 ? 1 : 2;
    return `${scaledRate.toFixed(decimalPlaces)} ${units[unitIndex]}`;
  }

  function formatDuration(rawSeconds) {
    const totalSeconds = Math.max(0, Number(rawSeconds) || 0);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = Math.floor(totalSeconds % 60);
    return hours > 0
      ? `${hours}时 ${String(minutes).padStart(2, "0")}分`
      : `${minutes}分 ${String(seconds).padStart(2, "0")}秒`;
  }

  function interfaceFromToken(interfaceToken) {
    return interfaceToken === AUTO_INTERFACE_TOKEN ? null : interfaceToken;
  }

  const utils = {
    AUTO_INTERFACE_TOKEN,
    formatTraffic,
    formatRate,
    formatDuration,
    interfaceFromToken,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = utils;
  } else {
    global.SRunPyUtils = utils;
  }
})(typeof window !== "undefined" ? window : globalThis);
