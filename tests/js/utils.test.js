"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const utils = require("../../srunpy/html/utils.js");

test("formatTraffic returns -- for empty or invalid values", () => {
  assert.equal(utils.formatTraffic(null), "--");
  assert.equal(utils.formatTraffic(undefined), "--");
  assert.equal(utils.formatTraffic(""), "--");
  assert.equal(utils.formatTraffic(-1), "--");
  assert.equal(utils.formatTraffic("not-a-number"), "--");
});

test("formatTraffic scales to MB and GB", () => {
  assert.equal(utils.formatTraffic(0), "0.00 MB");
  assert.equal(utils.formatTraffic(5 * 1024 * 1024), "5.00 MB");
  assert.equal(utils.formatTraffic(2 * 1024 ** 3), "2.00 GB");
});

test("formatRate picks units and decimal places", () => {
  assert.equal(utils.formatRate(null), "--");
  assert.equal(utils.formatRate(0), "0 B/s");
  assert.equal(utils.formatRate(1024), "1.00 KB/s");
  assert.equal(utils.formatRate(1234567), "1.18 MB/s");
  assert.equal(utils.formatRate(-5), "--");
});

test("formatDuration renders hours, minutes, and seconds", () => {
  assert.equal(utils.formatDuration(59), "0分 59秒");
  assert.equal(utils.formatDuration(3600 + 61), "1时 01分");
  assert.equal(utils.formatDuration(-5), "0分 00秒");
  assert.equal(utils.formatDuration("invalid"), "0分 00秒");
});

test("interfaceFromToken maps the auto token to null", () => {
  assert.equal(utils.interfaceFromToken("__auto__"), null);
  assert.equal(utils.interfaceFromToken("10.0.0.2"), "10.0.0.2");
  assert.equal(utils.AUTO_INTERFACE_TOKEN, "__auto__");
});
