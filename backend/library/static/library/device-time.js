"use strict";
function renderDeviceTimes() {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (!zone) return;
  const formatter = new Intl.DateTimeFormat(undefined, {
    timeZone: zone, dateStyle: "medium", timeStyle: "short",
  });
  const read = (id) => JSON.parse(document.getElementById(id)?.textContent || "{}");
  const label = (instant) => `${formatter.format(new Date(instant))} (${zone})`;
  const rows = read("device-timestamp-rows");
  document.querySelectorAll("#result_list tbody tr").forEach((row, index) => {
    const fields = rows[index]?.fields || {};
    for (const [field, instant] of Object.entries(fields)) {
      const cell = row.querySelector(`.field-${field}`);
      if (cell) cell.textContent = label(instant);
    }
  });
  for (const [field, instant] of Object.entries(read("device-timestamp-fields"))) {
    const row = document.querySelector(`.form-row.field-${field}`);
    if (!row) continue;
    const readonly = row.querySelector(".readonly");
    if (readonly) {
      readonly.textContent = label(instant);
    } else {
      // Do not reinterpret editable admin widgets: their posted values still
      // use Django's explicit operational timezone. Show a device-local preview.
      const preview = row.querySelector(".device-time-preview") || document.createElement("p");
      preview.className = "help device-time-preview";
      preview.textContent = `Device time: ${label(instant)}. Editable fields above use the server timezone.`;
      row.appendChild(preview);
    }
  }
}
document.addEventListener("DOMContentLoaded", renderDeviceTimes);
window.addEventListener("focus", renderDeviceTimes);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "hidden") renderDeviceTimes();
});
