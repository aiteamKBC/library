import { useEffect, useMemo, useState } from "react";
import { useAdminData } from "../../../hooks/useAdminData";
import type { Loan } from "../../../types/library";

const SORT_OPTIONS = ["newest", "oldest", "title"] as const;

function formatDate(date?: string | null) {
  if (!date) return "-";
  return new Date(date).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function formatBorrowerLine(loan: Loan) {
  const name = (loan.borrowerName ?? "").trim();
  const email = (loan.borrowerEmail ?? "").trim();

  if (!name && !email) return "Unknown borrower";
  if (name && email && name.toLowerCase() !== email.toLowerCase()) {
    return `${name} / ${email}`;
  }

  return name || email;
}

function getHistoryTimestamp(loan: Loan) {
  return new Date(loan.returnedAt ?? loan.borrowedAt ?? loan.requestedAt).getTime();
}

export default function CirculationHistoryManager() {
  const { loans, deleteLoan, bulkDeleteLoans } = useAdminData();
  const [search, setSearch] = useState("");
  const [sortBy, setSortBy] = useState<typeof SORT_OPTIONS[number]>("newest");
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [bulkDeleting, setBulkDeleting] = useState(false);

  const historyLoans = useMemo(() => loans.filter((loan) => loan.status === "returned"), [loans]);

  const filtered = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();

    const filteredLoans = historyLoans.filter((loan) => {
      const searchableFields = [
        loan.bookTitle,
        loan.accessionNumber,
        loan.borrowerName ?? "",
        loan.borrowerEmail ?? "",
        loan.borrowerPhone ?? "",
        loan.borrowerStudentId ?? "",
        loan.notes ?? "",
        loan.id,
      ].map((value) => value.toLowerCase());
      const matchesSearch = !normalizedSearch || searchableFields.some((value) => value.includes(normalizedSearch));
      return matchesSearch;
    });

    return filteredLoans.sort((a, b) => {
      if (sortBy === "title") {
        return a.bookTitle.localeCompare(b.bookTitle);
      }

      const firstDate = getHistoryTimestamp(a);
      const secondDate = getHistoryTimestamp(b);
      return sortBy === "oldest" ? firstDate - secondDate : secondDate - firstDate;
    });
  }, [historyLoans, search, sortBy]);

  const filteredIdSet = useMemo(() => new Set(filtered.map((loan) => loan.id)), [filtered]);

  useEffect(() => {
    setSelectedIds((previous) => {
      const next = previous.filter((id) => filteredIdSet.has(id));
      return next.length === previous.length ? previous : next;
    });
  }, [filteredIdSet]);

  const summary = useMemo(
    () => {
      const now = new Date();
      const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
      const currentDay = now.getDay();
      const diffToMonday = currentDay === 0 ? 6 : currentDay - 1;
      const startOfWeek = new Date(now.getFullYear(), now.getMonth(), now.getDate() - diffToMonday).getTime();
      const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1).getTime();

      return {
        total: historyLoans.length,
        today: historyLoans.filter((loan) => getHistoryTimestamp(loan) >= startOfToday).length,
        thisWeek: historyLoans.filter((loan) => getHistoryTimestamp(loan) >= startOfWeek).length,
        thisMonth: historyLoans.filter((loan) => getHistoryTimestamp(loan) >= startOfMonth).length,
      };
    },
    [historyLoans],
  );

  const allShownSelected = filtered.length > 0 && filtered.every((loan) => selectedIds.includes(loan.id));
  const hasActiveFilters = search.trim().length > 0 || sortBy !== "newest";

  const exportCsv = () => {
    const headers = [
      "Book Title",
      "Status",
      "Loan Type",
      "Borrower Name",
      "Borrower Email",
      "Borrower Phone",
      "Student ID",
      "Copy Number",
      "Requested At",
      "Requested From",
      "Due Date",
      "Borrowed At",
      "Returned At",
      "Notes",
    ];

    const rows = filtered.map((loan) => [
      loan.bookTitle,
      loan.status,
      loan.loanType ?? "borrow",
      loan.borrowerName ?? "",
      loan.borrowerEmail ?? "",
      loan.borrowerPhone ?? "",
      loan.borrowerStudentId ?? "",
      loan.accessionNumber,
      formatDate(loan.requestedAt),
      formatDate(loan.requestedFrom),
      formatDate(loan.dueDate),
      formatDate(loan.borrowedAt),
      formatDate(loan.returnedAt),
      loan.notes ?? "",
    ]);

    const csv = [headers, ...rows]
      .map((row) => row.map((cell) => `"${String(cell).replace(/"/g, "\"\"")}"`).join(","))
      .join("\n");

    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const stamp = new Date().toISOString().slice(0, 10);
    link.href = url;
    link.download = `circulation-history-${stamp}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const toggleRowSelection = (loanId: string) => {
    setSelectedIds((previous) => (
      previous.includes(loanId)
        ? previous.filter((id) => id !== loanId)
        : [...previous, loanId]
    ));
  };

  const handleSelectAllShownAction = () => {
    if (allShownSelected) {
      setSelectedIds((previous) => previous.filter((id) => !filteredIdSet.has(id)));
      return;
    }

    setSelectedIds((previous) => {
      const next = new Set(previous);
      filtered.forEach((loan) => next.add(loan.id));
      return Array.from(next);
    });
  };

  const handleDeleteOne = async (loan: Loan) => {
    const confirmed = window.confirm(`Delete the record for "${loan.bookTitle}"?\n\nThis action cannot be undone.`);
    if (!confirmed) return;

    setDeletingId(loan.id);
    try {
      await deleteLoan(loan.id);
      setSelectedIds((previous) => previous.filter((id) => id !== loan.id));
    } finally {
      setDeletingId(null);
    }
  };

  const handleBulkDelete = async (ids: string[], scopeLabel: string) => {
    if (!ids.length) return;
    const confirmed = window.confirm(`Delete ${ids.length} ${scopeLabel} record${ids.length === 1 ? "" : "s"}?\n\nThis action cannot be undone.`);
    if (!confirmed) return;

    setBulkDeleting(true);
    try {
      await bulkDeleteLoans(ids);
      setSelectedIds([]);
    } finally {
      setBulkDeleting(false);
    }
  };

  const resetView = () => {
    setSearch("");
    setSortBy("newest");
    setSelectedIds([]);
  };

  return (
    <>
      <div className="max-w-7xl space-y-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-xl font-bold text-gray-900" style={{ fontFamily: "'Playfair Display', serif" }}>
              History
            </h2>
            <p className="mt-0.5 text-sm text-gray-400">
              Review completed returns and remove old history records from one place.
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            {hasActiveFilters && (
              <button
                onClick={resetView}
                className="inline-flex items-center justify-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm font-semibold text-gray-600 transition-colors hover:border-[#442F73]/20 hover:text-[#442F73]"
              >
                <i className="ri-refresh-line" />
                Reset view
              </button>
            )}
            <button
              onClick={exportCsv}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-[#442F73] px-4 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-[#241453] whitespace-nowrap"
            >
              <i className="ri-download-2-line" />
              Export CSV
            </button>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-2xl border border-gray-200 bg-white p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Total Returned Records</p>
            <p className="mt-2 text-2xl font-bold text-gray-900">{summary.total}</p>
          </div>
          <div className="rounded-2xl border border-gray-200 bg-white p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Returned Today</p>
            <p className="mt-2 text-2xl font-bold text-[#442F73]">{summary.today}</p>
          </div>
          <div className="rounded-2xl border border-gray-200 bg-white p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Returned This Week</p>
            <p className="mt-2 text-2xl font-bold text-emerald-600">{summary.thisWeek}</p>
          </div>
          <div className="rounded-2xl border border-gray-200 bg-white p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">Returned This Month</p>
            <p className="mt-2 text-2xl font-bold text-amber-600">{summary.thisMonth}</p>
          </div>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white p-4 md:p-5">
          <div className="flex flex-col gap-3 xl:flex-row">
            <div className="relative flex-1">
              <i className="ri-search-line absolute left-3.5 top-1/2 -translate-y-1/2 text-sm text-gray-400" />
              <input
                type="text"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search returned records by title, borrower, email, phone, copy number, note, or record ID..."
                className="w-full rounded-xl border border-gray-200 bg-white py-2.5 pl-10 pr-4 text-sm text-gray-800 outline-none focus:border-[#442F73] placeholder-gray-400"
              />
            </div>

            <div className="flex flex-col gap-3 sm:flex-row xl:w-auto">
              <select
                value={sortBy}
                onChange={(event) => setSortBy(event.target.value as typeof SORT_OPTIONS[number])}
                className="min-w-40 rounded-xl border border-gray-200 bg-white px-4 py-2.5 text-sm text-gray-700 outline-none focus:border-[#442F73]"
              >
                <option value="newest">Latest returns</option>
                <option value="oldest">Oldest returns</option>
                <option value="title">Title A-Z</option>
              </select>
            </div>
          </div>

          <div
            className={`mt-4 flex flex-col gap-3 rounded-2xl p-4 lg:flex-row lg:items-center lg:justify-between ${
              selectedIds.length
                ? "border border-[#442F73]/12 bg-[#F7F2FF]"
                : "border border-dashed border-[#E9D9BD] bg-[#F9F4EC]"
            }`}
          >
            <div>
              <p className="text-sm font-semibold text-[#241453]">
                Showing {filtered.length} of {summary.total} record{summary.total === 1 ? "" : "s"}
              </p>
              <p className="mt-1 text-xs text-gray-500">
                {selectedIds.length
                  ? `${selectedIds.length} selected${allShownSelected ? " across all shown records" : ""}.`
                  : hasActiveFilters
                    ? "Filters are active. Narrow the history or reset the view."
                    : "Use search, filters, or bulk actions to manage the history faster."}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={handleSelectAllShownAction}
                disabled={!filtered.length || bulkDeleting}
                className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition-colors hover:border-[#442F73]/20 hover:text-[#442F73] disabled:cursor-not-allowed disabled:opacity-50"
              >
                <i className={allShownSelected ? "ri-close-circle-line" : "ri-checkbox-multiple-line"} />
                {allShownSelected ? "Deselect All Shown" : "Select All Shown"}
              </button>
              {selectedIds.length > 0 && (
                <button
                  onClick={() => void handleBulkDelete(selectedIds, "selected")}
                  disabled={bulkDeleting}
                  className="inline-flex items-center gap-2 rounded-xl bg-rose-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <i className={bulkDeleting ? "ri-loader-4-line animate-spin" : "ri-delete-bin-5-line"} />
                  Delete Selected ({selectedIds.length})
                </button>
              )}
            </div>
          </div>
        </div>

        <div className="hidden overflow-hidden rounded-2xl border border-gray-200 bg-white lg:block">
          <div className="grid grid-cols-[44px_2fr_1.75fr_1.4fr_0.95fr_92px] gap-4 border-b border-gray-100 px-5 py-4 text-[11px] font-semibold uppercase tracking-wide text-gray-400">
            <label className="flex items-center justify-center">
                <input
                  type="checkbox"
                  checked={allShownSelected}
                  onChange={(event) => {
                    if (event.target.checked) {
                      setSelectedIds(filtered.map((loan) => loan.id));
                    } else {
                      setSelectedIds([]);
                    }
                  }}
                  className="h-4 w-4 rounded border-gray-300 text-[#442F73] focus:ring-[#442F73]"
                />
            </label>
            <span>Book</span>
            <span>Borrower</span>
            <span>Borrowed / Returned</span>
            <span>Copy</span>
            <span>Actions</span>
          </div>

          {filtered.map((loan) => (
            <div
              key={loan.id}
              className={`grid grid-cols-[44px_2fr_1.75fr_1.4fr_0.95fr_92px] gap-4 border-b border-gray-100 px-5 py-4 last:border-b-0 ${selectedIds.includes(loan.id) ? "bg-[#F9F4EC]" : ""}`}
            >
              <label className="flex items-start justify-center pt-1">
                <input
                  type="checkbox"
                  checked={selectedIds.includes(loan.id)}
                  onChange={() => toggleRowSelection(loan.id)}
                  className="h-4 w-4 rounded border-gray-300 text-[#442F73] focus:ring-[#442F73]"
                />
              </label>
              <div>
                <p className="text-sm font-semibold text-gray-900">{loan.bookTitle}</p>
                {loan.notes && <p className="mt-1 line-clamp-2 text-xs text-gray-400">{loan.notes}</p>}
                <p className="mt-1 text-[11px] text-gray-400">ID: {loan.id}</p>
              </div>
              <div>
                <p className="text-sm text-gray-700">{formatBorrowerLine(loan)}</p>
                <p className="mt-1 text-xs text-gray-400">{loan.borrowerPhone || "No phone number"}</p>
              </div>
              <div>
                <p className="text-sm text-gray-700">Borrowed: {formatDate(loan.borrowedAt)}</p>
                <p className="mt-1 text-xs text-emerald-600">Returned: {formatDate(loan.returnedAt)}</p>
                <p className="mt-1 text-xs text-gray-400">Due: {formatDate(loan.dueDate)}</p>
              </div>
              <div>
                <p className="text-sm text-gray-700">{loan.accessionNumber}</p>
                <p className="mt-1 text-xs text-gray-400">{loan.borrowerStudentId || "No student ID"}</p>
              </div>
              <div className="flex flex-col gap-2">
                <button
                  onClick={() => void handleDeleteOne(loan)}
                  disabled={deletingId === loan.id}
                  className="inline-flex items-center justify-center gap-1 rounded-xl border border-gray-200 bg-white px-3 py-2 text-xs font-semibold text-gray-500 transition-colors hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <i className={deletingId === loan.id ? "ri-loader-4-line animate-spin" : "ri-delete-bin-line"} />
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>

        <div className="space-y-3 lg:hidden">
          {filtered.map((loan) => (
            <div key={loan.id} className={`space-y-4 rounded-2xl border border-gray-200 bg-white p-4 ${selectedIds.includes(loan.id) ? "ring-2 ring-[#442F73]/10" : ""}`}>
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    checked={selectedIds.includes(loan.id)}
                    onChange={() => toggleRowSelection(loan.id)}
                    className="mt-1 h-4 w-4 rounded border-gray-300 text-[#442F73] focus:ring-[#442F73]"
                  />
                  <div>
                    <p className="text-sm font-semibold text-gray-900">{loan.bookTitle}</p>
                    <p className="mt-1 text-xs text-gray-400">{formatBorrowerLine(loan)}</p>
                    <p className="mt-1 text-[11px] text-gray-400">ID: {loan.id}</p>
                  </div>
                </div>
                <span className="inline-flex rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700">
                  Returned
                </span>
              </div>

              <div className="grid gap-2 text-xs text-gray-500 sm:grid-cols-2">
                <p><span className="font-semibold text-gray-700">Borrowed:</span> {formatDate(loan.borrowedAt)}</p>
                <p><span className="font-semibold text-gray-700">Returned:</span> {formatDate(loan.returnedAt)}</p>
                <p><span className="font-semibold text-gray-700">Due:</span> {formatDate(loan.dueDate)}</p>
                <p><span className="font-semibold text-gray-700">Copy:</span> {loan.accessionNumber}</p>
                <p><span className="font-semibold text-gray-700">Phone:</span> {loan.borrowerPhone || "No phone number"}</p>
                <p><span className="font-semibold text-gray-700">Student ID:</span> {loan.borrowerStudentId || "No student ID"}</p>
              </div>

              {loan.notes && (
                <div className="rounded-xl border border-gray-100 bg-gray-50 px-3 py-2">
                  <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-gray-400">Notes</p>
                  <p className="text-xs leading-relaxed text-gray-600">{loan.notes}</p>
                </div>
              )}

              <div className="flex flex-wrap gap-2">
                <button
                  onClick={() => void handleDeleteOne(loan)}
                  disabled={deletingId === loan.id}
                  className="inline-flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-4 py-2 text-xs font-semibold text-gray-500 transition-colors hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <i className={deletingId === loan.id ? "ri-loader-4-line animate-spin" : "ri-delete-bin-line"} />
                  Delete Row
                </button>
              </div>
            </div>
          ))}
        </div>

        {filtered.length === 0 && (
          <div className="rounded-2xl border border-gray-200 bg-white py-16 text-center">
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-gray-50">
              <i className="ri-history-line text-2xl text-gray-300" />
            </div>
            <p className="mb-1 font-medium text-gray-500">No returned records found</p>
            <p className="text-sm text-gray-400">Completed returns will appear here after books are marked as returned.</p>
          </div>
        )}
      </div>
    </>
  );
}
