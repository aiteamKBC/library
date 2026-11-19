import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import net from "node:net";
import test from "node:test";
import { runInNewContext } from "node:vm";
import ts from "typescript";
import { formatLibraryDate, formatLibraryTimestamp, getDeviceTimeZone, libraryCalendarDate, libraryCalendarDayTimestamp } from "./libraryDates.ts";
import { getReturnTimingSummary } from "./loanReturnTiming.ts";

const forbidden = () => { throw new Error("Network access is forbidden in frontend tests."); };
net.Socket.prototype.connect = forbidden;
globalThis.fetch = forbidden;

test("DateFields keep their calendar date in every browser timezone", () => {
  const original = process.env.TZ;
  try {
    for (const zone of ["UTC", "America/Los_Angeles", "Pacific/Auckland", "Africa/Cairo", "Europe/London", "America/New_York", "Asia/Dubai"]) {
      process.env.TZ = zone;
      assert.equal(formatLibraryDate("2026-07-15"), "15 Jul 2026");
      assert.equal(libraryCalendarDate("2026-07-15"), "2026-07-15");
      assert.equal(libraryCalendarDayTimestamp("2026-07-15"), Date.UTC(2026, 6, 15));
    }
  } finally {
    if (original === undefined) delete process.env.TZ;
    else process.env.TZ = original;
  }
});

test("London viewers retain the existing GMT/BST date-boundary coverage", () => {
  const previous = process.env.TZ;
  process.env.TZ = "Europe/London";
  try {
  assert.equal(libraryCalendarDate("2026-01-15T23:30:00Z"), "2026-01-15");
  assert.equal(libraryCalendarDate("2026-07-15T23:30:00Z"), "2026-07-16");
  assert.equal(formatLibraryDate("2026-07-15T23:30:00Z"), "16 Jul 2026");
  assert.equal(libraryCalendarDate("2026-07-16T00:30:00+03:00"), "2026-07-15");
  assert.equal(libraryCalendarDayTimestamp("2026-07-16T00:30:00+03:00"), libraryCalendarDayTimestamp("2026-07-15"));
  for (const value of ["2026-03-29T00:30:00Z", "2026-03-29T01:30:00Z"]) {
    assert.equal(libraryCalendarDate(value), "2026-03-29");
  }
  for (const value of ["2026-10-25T00:30:00Z", "2026-10-25T01:30:00Z"]) {
    assert.equal(libraryCalendarDate(value), "2026-10-25");
  }
  assert.equal(formatLibraryDate(null), "-");
  assert.equal(formatLibraryDate("invalid"), "-");
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});

let moduleNumber = 0;
async function loadApi() {
  const source = (await readFile(new URL("./api.ts", import.meta.url), "utf8"))
    .replaceAll("import.meta.env", "({})")
    .replace('"./libraryDates"', JSON.stringify(new URL("./libraryDates.ts", import.meta.url).href));
  const javascript = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(`${javascript}\n// isolated ${moduleNumber++}`).toString("base64")}`);
}

test("frontend preview consumes the backend date without caching or recalculating", async () => {
  // Compile in memory; do not invoke Vite or load any .env file.
  const { api } = await loadApi();
  globalThis.localStorage = { getItem: () => null };
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return new Response(JSON.stringify({ dueDate: calls.length === 1 ? "2026-11-20" : "2026-11-19" }));
  };
  try {
    assert.deepEqual(await api.previewLoanReturnDate("synthetic-loan", 5), { dueDate: "2026-11-20" });
    assert.deepEqual(await api.previewLoanReturnDate("synthetic-loan", 5), { dueDate: "2026-11-19" });
    assert.equal(calls.length, 2);
    assert.equal(calls[0].url, "/api/loans/synthetic-loan/return-date-preview/?deliveryDays=5");
    assert.equal(calls[0].init.cache, "no-store");
  } finally {
    globalThis.fetch = forbidden;
    delete globalThis.localStorage;
  }
});

test("the same UTC instant is displayed in the device timezone, with seasonal offsets", () => {
  const previous = process.env.TZ;
  try {
    for (const [zone, winter, summer] of [
      ["Africa/Cairo", "00:30", "01:30"],
      ["Europe/London", "22:30", "23:30"],
      ["America/New_York", "17:30", "18:30"],
      ["Asia/Dubai", "02:30", "02:30"],
    ]) {
      process.env.TZ = zone;
      assert.equal(getDeviceTimeZone(), Intl.DateTimeFormat().resolvedOptions().timeZone);
      const options = { hour: "2-digit", minute: "2-digit", hourCycle: "h23" };
      assert.equal(formatLibraryDate("2026-01-15T22:30:00Z", options), winter);
      assert.equal(formatLibraryDate("2026-07-15T22:30:00Z", options), summer);
      assert.ok(formatLibraryTimestamp("2026-01-15T22:30:00Z").includes(winter));
      assert.ok(formatLibraryTimestamp("2026-07-15T22:30:00Z").includes(summer));
      assert.equal(formatLibraryDate("2026-07-15"), "15 Jul 2026");
    }
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});

test("explicit offsets identify the same instant and are never converted twice", () => {
  const previous = process.env.TZ;
  const values = ["2026-07-15T23:30:00Z", "2026-07-16T02:30:00+03:00", "2026-07-16T00:30:00+01:00",
    "2026-07-15T19:30:00-04:00", "2026-07-16T03:30:00+04:00"];
  try {
    for (const zone of ["Africa/Cairo", "Europe/London", "America/New_York", "Asia/Dubai"]) {
      process.env.TZ = zone;
      const expected = formatLibraryTimestamp(values[0]);
      for (const value of values) assert.equal(formatLibraryTimestamp(value), expected);
    }
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});

test("different national DST dates and missing/repeated local hours render correctly", () => {
  const previous = process.env.TZ;
  try {
    for (const [day, hours] of [
      ["2026-03-15", ["12:30", "10:30", "06:30", "14:30"]],
      ["2026-03-30", ["12:30", "11:30", "06:30", "14:30"]],
      ["2026-04-30", ["13:30", "11:30", "06:30", "14:30"]],
      ["2026-10-28", ["13:30", "10:30", "06:30", "14:30"]],
      ["2026-11-05", ["12:30", "10:30", "05:30", "14:30"]],
    ]) {
      for (const [index, zone] of ["Africa/Cairo", "Europe/London", "America/New_York", "Asia/Dubai"].entries()) {
        process.env.TZ = zone;
        assert.ok(formatLibraryTimestamp(`${day}T10:30:00Z`).includes(hours[index]), `${zone} on ${day}`);
      }
    }
    for (const [zone, before, after, hourBefore, hourAfter] of [
      ["Europe/London", "2026-03-29T00:30:00Z", "2026-03-29T01:30:00Z", "00:30", "02:30"],
      ["Europe/London", "2026-10-25T00:30:00Z", "2026-10-25T01:30:00Z", "01:30", "01:30"],
      ["America/New_York", "2026-03-08T06:30:00Z", "2026-03-08T07:30:00Z", "01:30", "03:30"],
      ["America/New_York", "2026-11-01T05:30:00Z", "2026-11-01T06:30:00Z", "01:30", "01:30"],
    ]) {
      process.env.TZ = zone;
      const first = formatLibraryTimestamp(before);
      const second = formatLibraryTimestamp(after);
      assert.ok(first.includes(hourBefore));
      assert.ok(second.includes(hourAfter));
      assert.notEqual(first, second, "offset labels distinguish repeated local hours");
    }
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});

test("historical dates retain their calendar day and unlabelled timestamps are not guessed", () => {
  const previous = process.env.TZ;
  try {
    for (const zone of ["Africa/Cairo", "Europe/London", "America/New_York", "Asia/Dubai"]) {
      process.env.TZ = zone;
      assert.equal(formatLibraryDate("1899-12-31"), "31 Dec 1899");
      assert.equal(formatLibraryTimestamp("1999-12-31"), "31 Dec 1999");
      assert.equal(formatLibraryDate("2026-02-31"), "-");
      assert.equal(libraryCalendarDate("2026-02-31"), "");
      assert.equal(libraryCalendarDayTimestamp("2026-02-31"), null);
      for (const value of ["2026-07-15T23:30:00", "2026-07-15 23:30:00", "2026-02-31T12:00:00Z"]) {
        assert.equal(formatLibraryTimestamp(value), "-");
        assert.equal(libraryCalendarDate(value), "");
      }
    }
    assert.equal(libraryCalendarDate("2026-07-15T23:30:00Z", "invalid/zone"), "");
    assert.equal(formatLibraryDate("2026-07-15T23:30:00Z", { timeZone: "invalid/zone" }), "-");
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});

test("history lateness uses the backend result, independently of the viewer", () => {
  const previous = process.env.TZ;
  try {
    for (const zone of ["Africa/Cairo", "America/New_York", "Asia/Dubai", "Europe/London"]) {
      process.env.TZ = zone;
      assert.deepEqual(getReturnTimingSummary({ dueDate: "2026-07-15", returnedAt: "2026-07-15T23:30:00Z", returnDaysLate: 1 }),
        { late: true, daysLate: 1, label: "Late by 1 day" });
      assert.equal(getReturnTimingSummary({ dueDate: "2026-07-15", returnedAt: "2026-07-15T23:30:00Z" }).label, "Return timing unavailable");
    }
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});

test("authenticated timezone capture consumes the durable preference response and device changes", async () => {
  const previous = process.env.TZ;
  const { observeAuthenticatedDeviceTimezone } = await loadApi();
  let token = null;
  const calls = [];
  globalThis.localStorage = { getItem: () => token };
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    const zone = JSON.parse(init.body).timeZone;
    return new Response(JSON.stringify({ observedTimeZone: zone, savedTimeZone: zone, saved: true, status: "saved", source: "browser", updatedAt: "2026-07-15T12:00:00Z" }));
  };
  try {
    assert.equal(await observeAuthenticatedDeviceTimezone(), null);
    assert.equal(calls.length, 0);
    token = "synthetic-student-token";
    process.env.TZ = "Africa/Cairo";
    assert.equal((await observeAuthenticatedDeviceTimezone()).saved, true);
    await observeAuthenticatedDeviceTimezone();
    assert.equal(calls.length, 1);
    process.env.TZ = "America/New_York";
    await observeAuthenticatedDeviceTimezone();
    assert.equal(calls.length, 2);
    assert.deepEqual(JSON.parse(calls[1].init.body), { timeZone: "America/New_York" });
    assert.equal(calls[1].init.headers.get("Authorization"), "Token synthetic-student-token");
    token = "synthetic-admin-token";
    await observeAuthenticatedDeviceTimezone();
    assert.equal(calls.length, 3);
    await observeAuthenticatedDeviceTimezone({ force: true });
    assert.equal(calls.length, 4, "returning to an already-open device reasserts its browser preference");
  } finally {
    globalThis.fetch = forbidden;
    delete globalThis.localStorage;
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});

test("native Django Admin formats UTC metadata locally without rewriting date-only or input values", async () => {
  const source = await readFile(new URL("../../../backend/library/static/library/device-time.js", import.meta.url), "utf8");
  const previous = process.env.TZ;
  const instant = "2026-07-15T23:30:00+00:00";
  const readonly = { textContent: "Server value" };
  const dateOnly = { textContent: "15 Jul 2026" };
  const input = { value: "2026-07-16 00:30:00" };
  const stampCell = { textContent: "Server value" };
  let preview = null;
  let appends = 0;
  const callbacks = {};
  const formRows = {
    ".form-row.field-approved_at": { querySelector: () => readonly },
    ".form-row.field-requested_at": {
      querySelector: (selector) => selector === ".readonly" ? null : preview,
      appendChild: (element) => { if (!preview) appends++; preview = element; },
    },
  };
  const document = {
    visibilityState: "visible",
    addEventListener: (name, callback) => { callbacks[name] = callback; },
    getElementById: (id) => ({ textContent: JSON.stringify(id === "device-timestamp-rows"
      ? [{ fields: { approved_at: instant } }] : { approved_at: instant, requested_at: instant }) }),
    querySelectorAll: () => [{ querySelector: (selector) => selector === ".field-approved_at" ? stampCell : dateOnly }],
    querySelector: (selector) => formRows[selector],
    createElement: () => ({ textContent: "", className: "" }),
  };
  try {
    runInNewContext(source, { document, window: { addEventListener: (name, callback) => { callbacks[name] = callback; } }, Intl, Date });
    process.env.TZ = "America/New_York";
    callbacks.DOMContentLoaded();
    assert.match(readonly.textContent, /America\/New_York/);
    assert.match(stampCell.textContent, /America\/New_York/);
    process.env.TZ = "Africa/Cairo";
    callbacks.focus();
    assert.match(readonly.textContent, /Africa\/Cairo/);
    assert.equal(dateOnly.textContent, "15 Jul 2026");
    assert.equal(input.value, "2026-07-16 00:30:00");
    assert.equal(appends, 1);
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});

test("explicit timezone preference uses its own authenticated endpoint and survives browser observation", async () => {
  const { api, observeAuthenticatedDeviceTimezone } = await loadApi();
  const previous = process.env.TZ;
  const calls = [];
  globalThis.localStorage = { getItem: () => "synthetic-own-account-token" };
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    if (url.endsWith("timezone-preference/")) {
      return new Response(JSON.stringify({ user: { timeZone: "Asia/Dubai", timeZoneSource: "manual" }, status: "saved" }));
    }
    return new Response(JSON.stringify({ observedTimeZone: JSON.parse(init.body).timeZone,
      savedTimeZone: "Asia/Dubai", saved: false, status: "manual_preserved", source: "manual", updatedAt: "2026-07-15T12:00:00Z" }));
  };
  try {
    process.env.TZ = "America/New_York";
    const response = await api.setMyTimezone("Asia/Dubai", "manual");
    assert.equal(response.user.timeZoneSource, "manual");
    assert.equal(calls[0].url, "/api/auth/timezone-preference/");
    assert.equal(calls[0].init.method, "PUT");
    assert.deepEqual(JSON.parse(calls[0].init.body), { timeZone: "Asia/Dubai", source: "manual" });
    const observed = await observeAuthenticatedDeviceTimezone();
    assert.equal(observed.savedTimeZone, "Asia/Dubai");
    assert.equal(observed.status, "manual_preserved");
  } finally {
    globalThis.fetch = forbidden;
    delete globalThis.localStorage;
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});
