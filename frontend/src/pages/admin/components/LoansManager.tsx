import { useMemo, useState } from "react";
import { useAdminData } from "../../../hooks/useAdminData";
import type { Loan } from "../../../types/library";

type SubTab = "queue" | "active" | "notify";

const ACTIVE_STATUSES = ["approved", "borrowed", "reserved", "overdue"] as const;

const statusStyles: Record<string, string> = {
  approved: "bg-indigo-50 text-indigo-700 border border-indigo-200",
  borrowed: "bg-amber-50 text-amber-700 border border-amber-200",
  reserved: "bg-sky-50 text-sky-700 border border-sky-200",
  overdue: "bg-rose-50 text-rose-600 border border-rose-200",
  requested: "bg-gray-100 text-gray-600 border border-gray-200",
  cancelled: "bg-gray-100 text-gray-400 border border-gray-200",
  returned: "bg-emerald-50 text-emerald-700 border border-emerald-200",
};

function formatDate(date?: string | null) {
  if (!date) return "-";
  return new Date(date).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

function BorrowerCard({ loan }: { loan: Loan }) {
  const name = (loan.borrowerName ?? "").trim();
  const email = (loan.borrowerEmail ?? "").trim();
  const initials = name
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <div className="flex items-center gap-3 min-w-0">
      <div className="w-9 h-9 flex-none rounded-full bg-[#442F73]/10 flex items-center justify-center">
        <span className="text-xs font-bold text-[#442F73]">{initials || "?"}</span>
      </div>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-gray-900 truncate">{name || "Unknown"}</p>
        <p className="text-xs text-gray-400 truncate">{email}</p>
        {loan.borrowerPhone && (
          <p className="text-xs text-gray-400">{loan.borrowerPhone}</p>
        )}
      </div>
    </div>
  );
}

// ─── Borrow Queue ─────────────────────────────────────────────────────────────

interface BookGroup {
  key: string;
  bookTitle: string;
  requests: Loan[];
}

interface DateEdit {
  requestedFrom: string;
  dueDate: string;
}

function BorrowQueue() {
  const { loans, approveLoan, updateLoan } = useAdminData();
  const [confirming, setConfirming] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [editingDates, setEditingDates] = useState<string | null>(null);
  const [dateEdit, setDateEdit] = useState<DateEdit>({ requestedFrom: "", dueDate: "" });
  const [savingDates, setSavingDates] = useState(false);

  const pending = useMemo(
    () => loans.filter((l) => l.status === "requested" && l.loanType !== "notify"),
    [loans],
  );

  const groups = useMemo<BookGroup[]>(() => {
    const map = new Map<string, BookGroup>();
    for (const loan of pending) {
      const key = loan.resourceId ?? loan.bookTitle;
      if (!map.has(key)) {
        map.set(key, { key, bookTitle: loan.bookTitle, requests: [] });
      }
      map.get(key)!.requests.push(loan);
    }
    return [...map.values()].sort((a, b) => b.requests.length - a.requests.length);
  }, [pending]);

  const handleConfirm = async (loanId: string) => {
    if (confirming) return;
    setConfirming(loanId);
    try {
      await approveLoan(loanId);
    } finally {
      setConfirming(null);
    }
  };

  const handleCancel = async (loanId: string) => {
    if (cancelling) return;
    setCancelling(loanId);
    try {
      await updateLoan(loanId, { status: "cancelled" });
    } finally {
      setCancelling(null);
    }
  };

  const openDateEdit = (loan: Loan) => {
    setEditingDates(loan.id);
    setDateEdit({
      requestedFrom: loan.requestedFrom ?? "",
      dueDate: loan.dueDate ?? "",
    });
  };

  const handleSaveDates = async (loanId: string) => {
    setSavingDates(true);
    try {
      await updateLoan(loanId, {
        requestedFrom: dateEdit.requestedFrom || undefined,
        dueDate: dateEdit.dueDate || undefined,
      });
      setEditingDates(null);
    } finally {
      setSavingDates(false);
    }
  };

  if (groups.length === 0) {
    return (
      <div className="bg-white rounded-2xl border border-gray-200 text-center py-16">
        <div className="w-14 h-14 mx-auto bg-gray-50 rounded-full flex items-center justify-center mb-4">
          <i className="ri-inbox-2-line text-gray-300 text-2xl" />
        </div>
        <p className="text-gray-500 font-medium mb-1">No pending borrow requests</p>
        <p className="text-gray-400 text-sm">New requests will appear here as students submit them.</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {groups.map((group) => (
        <div key={group.key} className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
          {/* Book header */}
          <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100 bg-gray-50/60">
            <div className="w-9 h-9 flex-none rounded-xl bg-[#442F73]/10 flex items-center justify-center">
              <i className="ri-book-2-line text-[#442F73] text-base" />
            </div>
            <p className="flex-1 font-bold text-gray-900 text-sm truncate">{group.bookTitle}</p>
            <span className="flex-none inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-[#442F73]/10 text-[#442F73] text-xs font-bold">
              <i className="ri-user-line" />
              {group.requests.length} {group.requests.length === 1 ? "request" : "requests"}
            </span>
          </div>

          {/* Requesters list */}
          <div className="divide-y divide-gray-100">
            {group.requests.map((loan) => (
              <div key={loan.id} className="flex flex-col gap-3 px-5 py-4">
                <div className="flex flex-col sm:flex-row sm:items-center gap-4">
                  <div className="flex-1 min-w-0">
                    <BorrowerCard loan={loan} />

                    {/* Date period row */}
                    {editingDates === loan.id ? (
                      <div className="mt-3 ml-12 space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="flex flex-col gap-0.5">
                            <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">From</label>
                            <input
                              type="date"
                              value={dateEdit.requestedFrom}
                              onChange={(e) => setDateEdit((p) => ({ ...p, requestedFrom: e.target.value }))}
                              className="text-xs border border-gray-200 rounded-lg px-2.5 py-1.5 outline-none focus:border-[#442F73] text-gray-700"
                            />
                          </div>
                          <div className="flex flex-col gap-0.5">
                            <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Until</label>
                            <input
                              type="date"
                              value={dateEdit.dueDate}
                              onChange={(e) => setDateEdit((p) => ({ ...p, dueDate: e.target.value }))}
                              className="text-xs border border-gray-200 rounded-lg px-2.5 py-1.5 outline-none focus:border-[#442F73] text-gray-700"
                            />
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => void handleSaveDates(loan.id)}
                            disabled={savingDates}
                            className="flex items-center gap-1 px-3 py-1.5 bg-[#442F73] hover:bg-[#241453] text-white text-xs font-semibold rounded-lg cursor-pointer transition-colors disabled:opacity-60"
                          >
                            {savingDates ? <i className="ri-loader-4-line animate-spin" /> : <i className="ri-save-line" />}
                            Save
                          </button>
                          <button
                            onClick={() => setEditingDates(null)}
                            className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-600 rounded-lg cursor-pointer transition-colors"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="mt-2 flex items-center gap-1.5 ml-12">
                        <i className="ri-calendar-line text-[#442F73]/50 text-xs" />
                        {(loan.requestedFrom || loan.dueDate) ? (
                          <span className="text-[11px] text-gray-500">
                            {formatDate(loan.requestedFrom)} → {formatDate(loan.dueDate)}
                          </span>
                        ) : (
                          <span className="text-[11px] text-gray-400 italic">No dates set</span>
                        )}
                        <button
                          onClick={() => openDateEdit(loan)}
                          className="ml-1 text-[10px] text-[#442F73]/60 hover:text-[#442F73] cursor-pointer transition-colors flex items-center gap-0.5"
                          title="Edit period"
                        >
                          <i className="ri-edit-line text-xs" />
                          Edit
                        </button>
                      </div>
                    )}

                    {loan.notes && (
                      <p className="mt-1.5 ml-12 text-xs text-gray-400 italic line-clamp-2">
                        "{loan.notes}"
                      </p>
                    )}
                    <p className="mt-1 ml-12 text-[11px] text-gray-400">
                      Requested {formatDate(loan.requestedAt)}
                    </p>
                  </div>

                  <div className="flex items-center gap-2 sm:flex-none ml-12 sm:ml-0">
                    <button
                      onClick={() => void handleConfirm(loan.id)}
                      disabled={!!confirming || !!cancelling}
                      className="flex items-center gap-1.5 px-4 py-2 bg-[#442F73] hover:bg-[#241453] text-white text-xs font-semibold rounded-xl cursor-pointer transition-colors disabled:opacity-60 disabled:cursor-not-allowed whitespace-nowrap"
                    >
                      {confirming === loan.id ? (
                        <>
                          <i className="ri-loader-4-line animate-spin" />
                          Confirming...
                        </>
                      ) : (
                        <>
                          <i className="ri-check-double-line" />
                          Confirm Borrow
                        </>
                      )}
                    </button>
                    <button
                      onClick={() => void handleCancel(loan.id)}
                      disabled={!!confirming || !!cancelling}
                      className="flex items-center gap-1 px-3 py-2 text-xs text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-xl cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed border border-transparent hover:border-red-100"
                    >
                      {cancelling === loan.id ? (
                        <i className="ri-loader-4-line animate-spin" />
                      ) : (
                        <i className="ri-close-line text-base" />
                      )}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>

          {group.requests.length > 1 && (
            <div className="px-5 py-3 border-t border-amber-100 bg-amber-50/50">
              <p className="text-[11px] text-amber-700 flex items-center gap-1.5">
                <i className="ri-information-line" />
                Confirming one borrower will start this loan. The remaining requests will stay in the queue for later review.
              </p>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Active Loans ─────────────────────────────────────────────────────────────

const ACTIVE_FILTER_TABS = ["all", ...ACTIVE_STATUSES] as const;

interface ActiveDateEdit {
  dueDate: string;
  notes: string;
}

function ActiveLoans() {
  const { loans, updateLoan, deleteLoan } = useAdminData();
  const [statusFilter, setStatusFilter] = useState<typeof ACTIVE_FILTER_TABS[number]>("all");
  const [search, setSearch] = useState("");
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const [editingLoan, setEditingLoan] = useState<string | null>(null);
  const [activeEdit, setActiveEdit] = useState<ActiveDateEdit>({ dueDate: "", notes: "" });
  const [savingEdit, setSavingEdit] = useState(false);

  const active = useMemo(
    () => loans.filter((l) => (ACTIVE_STATUSES as readonly string[]).includes(l.status)),
    [loans],
  );

  const counts = useMemo(
    () => ({
      all: active.length,
      approved: active.filter((l) => l.status === "approved").length,
      borrowed: active.filter((l) => l.status === "borrowed").length,
      reserved: active.filter((l) => l.status === "reserved").length,
      overdue: active.filter((l) => l.status === "overdue").length,
    }),
    [active],
  );

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return active.filter((loan) => {
      const matchStatus = statusFilter === "all" || loan.status === statusFilter;
      const matchSearch =
        !q ||
        [loan.bookTitle, loan.borrowerName ?? "", loan.borrowerEmail ?? "", loan.borrowerPhone ?? ""]
          .some((v) => v.toLowerCase().includes(q));
      return matchStatus && matchSearch;
    });
  }, [active, statusFilter, search]);

  const handleAction = async (id: string, updates: Partial<Loan>) => {
    if (actionInProgress) return;
    setActionInProgress(id);
    try {
      await updateLoan(id, updates);
    } finally {
      setActionInProgress(null);
    }
  };

  const handleDelete = async (id: string) => {
    if (actionInProgress) return;
    setActionInProgress(id);
    try {
      await deleteLoan(id);
    } finally {
      setActionInProgress(null);
    }
  };

  const openEdit = (loan: Loan) => {
    setEditingLoan(loan.id);
    setActiveEdit({ dueDate: loan.dueDate ?? "", notes: loan.notes ?? "" });
  };

  const handleSaveEdit = async (id: string) => {
    setSavingEdit(true);
    try {
      await updateLoan(id, {
        dueDate: activeEdit.dueDate || undefined,
        notes: activeEdit.notes,
      });
      setEditingLoan(null);
    } finally {
      setSavingEdit(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex gap-2 flex-wrap">
        {ACTIVE_FILTER_TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setStatusFilter(tab)}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold capitalize transition-all cursor-pointer whitespace-nowrap ${
              statusFilter === tab
                ? "bg-[#442F73] text-white"
                : "bg-white text-gray-500 border border-gray-200 hover:border-gray-300"
            }`}
          >
            {tab === "all" ? "All Active" : tab}
            <span
              className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${
                statusFilter === tab ? "bg-white/20 text-white" : "bg-gray-100 text-gray-500"
              }`}
            >
              {tab === "all" ? counts.all : (counts[tab as keyof typeof counts] ?? 0)}
            </span>
          </button>
        ))}
      </div>

      <div className="relative">
        <i className="ri-search-line absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by title, borrower name, email or phone..."
          className="w-full pl-10 pr-4 py-2.5 text-sm bg-white border border-gray-200 rounded-xl outline-none focus:border-[#442F73] text-gray-800 placeholder-gray-400"
        />
      </div>

      <div className="space-y-3">
        {filtered.map((loan) => (
          <div key={loan.id} className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <div className="p-5 space-y-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div>
                  <p className="font-bold text-gray-900 text-sm">{loan.bookTitle}</p>
                  <p className="text-[11px] text-gray-400 mt-0.5">{loan.accessionNumber}</p>
                </div>
                <span className={`px-2.5 py-1 text-xs font-semibold rounded-full capitalize ${statusStyles[loan.status]}`}>
                  {loan.status}
                </span>
              </div>

              <BorrowerCard loan={loan} />

              {editingLoan === loan.id ? (
                <div className="border border-[#442F73]/20 rounded-xl p-4 bg-[#442F73]/3 space-y-3">
                  <p className="text-[10px] font-bold text-[#442F73] uppercase tracking-wide">Edit Loan Details</p>
                  <div className="flex flex-wrap gap-4">
                    <div className="flex flex-col gap-1">
                      <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Due Date</label>
                      <input
                        type="date"
                        value={activeEdit.dueDate}
                        onChange={(e) => setActiveEdit((p) => ({ ...p, dueDate: e.target.value }))}
                        className="text-xs border border-gray-200 rounded-lg px-2.5 py-1.5 outline-none focus:border-[#442F73] text-gray-700"
                      />
                    </div>
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Notes</label>
                    <textarea
                      value={activeEdit.notes}
                      onChange={(e) => setActiveEdit((p) => ({ ...p, notes: e.target.value }))}
                      rows={2}
                      placeholder="Internal notes..."
                      className="text-xs border border-gray-200 rounded-lg px-2.5 py-1.5 outline-none focus:border-[#442F73] text-gray-700 resize-none"
                    />
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => void handleSaveEdit(loan.id)}
                      disabled={savingEdit}
                      className="flex items-center gap-1 px-3 py-1.5 bg-[#442F73] hover:bg-[#241453] text-white text-xs font-semibold rounded-lg cursor-pointer transition-colors disabled:opacity-60"
                    >
                      {savingEdit ? <i className="ri-loader-4-line animate-spin" /> : <i className="ri-save-line" />}
                      Save
                    </button>
                    <button
                      onClick={() => setEditingLoan(null)}
                      className="px-3 py-1.5 text-xs text-gray-400 hover:text-gray-600 rounded-lg cursor-pointer transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs">
                    <div>
                      <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Requested</p>
                      <p className="mt-0.5 text-gray-600">{formatDate(loan.requestedAt)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Due Date</p>
                      <p className={`mt-0.5 ${loan.status === "overdue" ? "text-rose-600 font-semibold" : "text-gray-600"}`}>
                        {formatDate(loan.dueDate)}
                      </p>
                    </div>
                    {loan.borrowedAt && (
                      <div>
                        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide">Borrowed</p>
                        <p className="mt-0.5 text-gray-600">{formatDate(loan.borrowedAt)}</p>
                      </div>
                    )}
                  </div>

                  {loan.notes && (
                    <p className="text-xs text-gray-400 italic border-t border-gray-100 pt-3">"{loan.notes}"</p>
                  )}
                </>
              )}
            </div>

            <div className="flex items-center gap-2 px-5 py-3 border-t border-gray-100 bg-gray-50/50 flex-wrap">
              {loan.status === "approved" && (
                <button
                  onClick={() => void handleAction(loan.id, { status: "borrowed" })}
                  disabled={actionInProgress === loan.id}
                  className="flex items-center gap-1.5 px-4 py-1.5 bg-amber-500 hover:bg-amber-600 text-white text-xs font-semibold rounded-lg cursor-pointer transition-colors disabled:opacity-60 disabled:cursor-not-allowed whitespace-nowrap"
                >
                  {actionInProgress === loan.id ? (
                    <i className="ri-loader-4-line animate-spin" />
                  ) : (
                    <i className="ri-book-open-line" />
                  )}
                  Mark as Borrowed
                </button>
              )}

              {(loan.status === "borrowed" || loan.status === "overdue") && (
                <button
                  onClick={() => void handleAction(loan.id, { status: "returned" })}
                  disabled={actionInProgress === loan.id}
                  className="flex items-center gap-1.5 px-4 py-1.5 bg-emerald-500 hover:bg-emerald-600 text-white text-xs font-semibold rounded-lg cursor-pointer transition-colors disabled:opacity-60 disabled:cursor-not-allowed whitespace-nowrap"
                >
                  {actionInProgress === loan.id ? (
                    <i className="ri-loader-4-line animate-spin" />
                  ) : (
                    <i className="ri-checkbox-circle-line" />
                  )}
                  Mark as Returned
                </button>
              )}

              {loan.status === "borrowed" && (
                <button
                  onClick={() => void handleAction(loan.id, { status: "overdue" })}
                  disabled={actionInProgress === loan.id}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-rose-50 hover:bg-rose-100 text-rose-600 text-xs font-semibold rounded-lg cursor-pointer transition-colors disabled:opacity-60 disabled:cursor-not-allowed border border-rose-200 whitespace-nowrap"
                >
                  <i className="ri-alarm-warning-line" />
                  Mark Overdue
                </button>
              )}

              {(loan.status === "approved" || loan.status === "reserved") && (
                <button
                  onClick={() => void handleAction(loan.id, { status: "cancelled" })}
                  disabled={actionInProgress === loan.id}
                  className="flex items-center gap-1 px-3 py-1.5 text-xs text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed border border-transparent hover:border-red-100 whitespace-nowrap"
                >
                  <i className="ri-close-line" />
                  Cancel
                </button>
              )}

              <button
                onClick={() => editingLoan === loan.id ? setEditingLoan(null) : openEdit(loan)}
                disabled={actionInProgress === loan.id}
                className={`ml-auto flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-lg cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed border ${
                  editingLoan === loan.id
                    ? "text-[#442F73] border-[#442F73]/20 bg-[#442F73]/5"
                    : "text-gray-400 border-transparent hover:text-[#442F73] hover:border-[#442F73]/20 hover:bg-[#442F73]/5"
                }`}
              >
                <i className="ri-edit-line" />
                Edit
              </button>
              <button
                onClick={() => void handleDelete(loan.id)}
                disabled={actionInProgress === loan.id}
                className="flex items-center gap-1 text-xs text-gray-300 hover:text-red-400 cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                <i className="ri-delete-bin-line" />
              </button>
            </div>
          </div>
        ))}

        {filtered.length === 0 && (
          <div className="bg-white rounded-2xl border border-gray-200 text-center py-16">
            <div className="w-14 h-14 mx-auto bg-gray-50 rounded-full flex items-center justify-center mb-4">
              <i className="ri-bookmark-3-line text-gray-300 text-2xl" />
            </div>
            <p className="text-gray-500 font-medium mb-1">No active loans found</p>
            <p className="text-gray-400 text-sm">Borrowed, reserved and overdue loans will appear here. Returned items are moved to History.</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Notify List ──────────────────────────────────────────────────────────────

function NotifyList() {
  const { loans, updateLoan, deleteLoan } = useAdminData();
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);

  const notifyLoans = useMemo(
    () => loans.filter((l) => l.loanType === "notify" && l.status === "requested"),
    [loans],
  );

  const groups = useMemo(() => {
    const map = new Map<string, { key: string; bookTitle: string; entries: Loan[] }>();
    for (const loan of notifyLoans) {
      const key = loan.resourceId ?? loan.bookTitle;
      if (!map.has(key)) map.set(key, { key, bookTitle: loan.bookTitle, entries: [] });
      map.get(key)!.entries.push(loan);
    }
    return [...map.values()].sort((a, b) => b.entries.length - a.entries.length);
  }, [notifyLoans]);

  const handleConvert = async (loan: Loan) => {
    if (actionInProgress) return;
    setActionInProgress(loan.id);
    try {
      await updateLoan(loan.id, { loanType: "borrow" });
    } finally {
      setActionInProgress(null);
    }
  };

  const handleCancel = async (id: string) => {
    if (actionInProgress) return;
    setActionInProgress(id);
    try {
      await updateLoan(id, { status: "cancelled" });
    } finally {
      setActionInProgress(null);
    }
  };

  const handleDelete = async (id: string) => {
    if (actionInProgress) return;
    setActionInProgress(id);
    try {
      await deleteLoan(id);
    } finally {
      setActionInProgress(null);
    }
  };

  if (groups.length === 0) {
    return (
      <div className="bg-white rounded-2xl border border-gray-200 text-center py-16">
        <div className="w-14 h-14 mx-auto bg-gray-50 rounded-full flex items-center justify-center mb-4">
          <i className="ri-notification-3-line text-gray-300 text-2xl" />
        </div>
        <p className="text-gray-500 font-medium mb-1">No notification registrations</p>
        <p className="text-gray-400 text-sm">People who register to be notified will appear here.</p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {groups.map((group) => (
        <div key={group.key} className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-4 border-b border-gray-100 bg-gray-50/60">
            <div className="w-9 h-9 flex-none rounded-xl bg-sky-500/10 flex items-center justify-center">
              <i className="ri-notification-3-line text-sky-600 text-base" />
            </div>
            <p className="flex-1 font-bold text-gray-900 text-sm truncate">{group.bookTitle}</p>
            <span className="flex-none inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-sky-500/10 text-sky-700 text-xs font-bold">
              <i className="ri-user-line" />
              {group.entries.length} {group.entries.length === 1 ? "waiting" : "waiting"}
            </span>
          </div>

          <div className="divide-y divide-gray-100">
            {group.entries.map((loan) => (
              <div key={loan.id} className="flex flex-col sm:flex-row sm:items-center gap-4 px-5 py-4">
                <div className="flex-1 min-w-0">
                  <BorrowerCard loan={loan} />
                  {loan.notes && (
                    <p className="mt-1.5 ml-12 text-xs text-gray-400 italic line-clamp-2">"{loan.notes}"</p>
                  )}
                  <p className="mt-1 ml-12 text-[11px] text-gray-400">Registered {formatDate(loan.requestedAt)}</p>
                </div>
                <div className="flex items-center gap-2 sm:flex-none ml-12 sm:ml-0">
                  <button
                    onClick={() => void handleConvert(loan)}
                    disabled={!!actionInProgress}
                    title="Move to Borrow Queue"
                    className="flex items-center gap-1.5 px-3 py-2 text-xs font-semibold text-[#442F73] bg-[#442F73]/8 hover:bg-[#442F73]/15 rounded-xl cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap border border-[#442F73]/15"
                  >
                    {actionInProgress === loan.id ? (
                      <i className="ri-loader-4-line animate-spin" />
                    ) : (
                      <i className="ri-arrow-right-up-line" />
                    )}
                    Move to Queue
                  </button>
                  <button
                    onClick={() => void handleCancel(loan.id)}
                    disabled={!!actionInProgress}
                    className="flex items-center gap-1 px-3 py-2 text-xs text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-xl cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed border border-transparent hover:border-red-100"
                  >
                    {actionInProgress === loan.id ? (
                      <i className="ri-loader-4-line animate-spin" />
                    ) : (
                      <i className="ri-close-line text-base" />
                    )}
                  </button>
                  <button
                    onClick={() => void handleDelete(loan.id)}
                    disabled={!!actionInProgress}
                    className="flex items-center gap-1 text-xs text-gray-300 hover:text-red-400 cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <i className="ri-delete-bin-line" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function LoansManager() {
  const { loans } = useAdminData();
  const [subTab, setSubTab] = useState<SubTab>("queue");

  const queueCount = useMemo(
    () => loans.filter((l) => l.status === "requested" && l.loanType !== "notify").length,
    [loans],
  );
  const activeCount = useMemo(
    () => loans.filter((l) => (ACTIVE_STATUSES as readonly string[]).includes(l.status)).length,
    [loans],
  );
  const notifyCount = useMemo(
    () => loans.filter((l) => l.loanType === "notify" && l.status === "requested").length,
    [loans],
  );

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900" style={{ fontFamily: "'Playfair Display', serif" }}>
          Loans & Reservations
        </h2>
        <p className="text-gray-400 text-sm mt-0.5">
          Confirm borrow requests and manage active circulation. Completed returns move to History automatically.
        </p>
      </div>

      {/* Sub-navigation */}
      <div className="flex gap-1 p-1 bg-gray-100 rounded-xl w-fit">
        <button
          onClick={() => setSubTab("queue")}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all cursor-pointer whitespace-nowrap ${
            subTab === "queue" ? "bg-white text-[#442F73] shadow-sm" : "text-gray-500 hover:text-gray-700"
          }`}
        >
          <i className="ri-inbox-line" />
          Borrow Queue
          {queueCount > 0 && (
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${subTab === "queue" ? "bg-[#442F73] text-white" : "bg-gray-300 text-gray-600"}`}>
              {queueCount}
            </span>
          )}
        </button>
        <button
          onClick={() => setSubTab("active")}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all cursor-pointer whitespace-nowrap ${
            subTab === "active" ? "bg-white text-[#442F73] shadow-sm" : "text-gray-500 hover:text-gray-700"
          }`}
        >
          <i className="ri-bookmark-3-line" />
          Active Loans
          {activeCount > 0 && (
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${subTab === "active" ? "bg-[#442F73] text-white" : "bg-gray-300 text-gray-600"}`}>
              {activeCount}
            </span>
          )}
        </button>
        <button
          onClick={() => setSubTab("notify")}
          className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold transition-all cursor-pointer whitespace-nowrap ${
            subTab === "notify" ? "bg-white text-sky-600 shadow-sm" : "text-gray-500 hover:text-gray-700"
          }`}
        >
          <i className="ri-notification-3-line" />
          Notify
          {notifyCount > 0 && (
            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${subTab === "notify" ? "bg-sky-500 text-white" : "bg-gray-300 text-gray-600"}`}>
              {notifyCount}
            </span>
          )}
        </button>
      </div>

      {subTab === "queue" && <BorrowQueue />}
      {subTab === "active" && <ActiveLoans />}
      {subTab === "notify" && <NotifyList />}
    </div>
  );
}
