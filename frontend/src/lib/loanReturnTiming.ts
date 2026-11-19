// Lateness is an authoritative backend result, never a viewer-local calculation.
export function getReturnTimingSummary(values: {
  dueDate?: string | null; returnedAt?: string | null; returnDaysLate?: number | null;
}) {
  if (!values.dueDate) return { late: false, daysLate: null, label: "Due date not recorded" };
  if (!values.returnedAt || values.returnDaysLate == null) {
    return { late: false, daysLate: null, label: "Return timing unavailable" };
  }
  const daysLate = values.returnDaysLate;
  return daysLate > 0
    ? { late: true, daysLate, label: `Late by ${daysLate} day${daysLate === 1 ? "" : "s"}` }
    : { late: false, daysLate: 0, label: "Returned on time" };
}
