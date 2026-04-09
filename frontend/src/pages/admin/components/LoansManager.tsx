import { useMemo, useState } from "react";
import { useAdminData } from "../../../hooks/useAdminData";
import type { Loan } from "../../../types/library";

const STATUS_TABS = ["all", "borrowed", "reserved", "returned", "overdue"] as const;

const statusStyles: Record<string, string> = {
  borrowed: "bg-amber-50 text-amber-700 border border-amber-200",
  reserved: "bg-sky-50 text-sky-700 border border-sky-200",
  returned: "bg-emerald-50 text-emerald-700 border border-emerald-200",
  overdue: "bg-rose-50 text-rose-600 border border-rose-200",
  requested: "bg-gray-100 text-gray-600 border border-gray-200",
  approved: "bg-indigo-50 text-indigo-700 border border-indigo-200",
  cancelled: "bg-gray-100 text-gray-500 border border-gray-200",
};

export default function LoansManager() {
  const { loans, updateLoan, deleteLoan } = useAdminData();
  const [statusFilter, setStatusFilter] = useState<typeof STATUS_TABS[number]>("all");
  const [search, setSearch] = useState("");

  const counts = useMemo(
    () => ({
      all: loans.length,
      borrowed: loans.filter((loan) => loan.status === "borrowed").length,
      reserved: loans.filter((loan) => loan.status === "reserved").length,
      returned: loans.filter((loan) => loan.status === "returned").length,
      overdue: loans.filter((loan) => loan.status === "overdue").length,
    }),
    [loans],
  );

  const filtered = useMemo(() => {
    return loans.filter((loan) => {
      const matchStatus = statusFilter === "all" || loan.status === statusFilter;
      const matchSearch =
        !search ||
        loan.bookTitle.toLowerCase().includes(search.toLowerCase()) ||
        (loan.borrowerName ?? "").toLowerCase().includes(search.toLowerCase()) ||
        (loan.borrowerEmail ?? "").toLowerCase().includes(search.toLowerCase()) ||
        (loan.borrowerPhone ?? "").toLowerCase().includes(search.toLowerCase()) ||
        (loan.borrowerStudentId ?? "").toLowerCase().includes(search.toLowerCase());
      return matchStatus && matchSearch;
    });
  }, [loans, search, statusFilter]);

  const getBorrowerSummary = (loan: Loan) => {
    const name = (loan.borrowerName ?? "").trim();
    const email = (loan.borrowerEmail ?? "").trim();

    if (!name && !email) {
      return "Unknown borrower";
    }

    return [name, email]
      .filter((value, index, values) => value && values.indexOf(value) === index)
      .join(" · ");
  };

  const formatBorrowerLine = (loan: Loan) => {
    const name = (loan.borrowerName ?? "").trim();
    const email = (loan.borrowerEmail ?? "").trim();

    if (!name && !email) {
      return "Unknown borrower";
    }

    if (name && email && name.toLowerCase() !== email.toLowerCase()) {
      return `${name} · ${email}`;
    }

    return name || email;
  };

  const markStatus = (loan: Loan, status: Loan["status"]) => {
    void updateLoan(loan.id, { status });
  };

  const canConfirmReservation = (loan: Loan) => {
    if (loan.status !== "reserved") {
      return false;
    }

    return !loans.some((otherLoan) => {
      if (otherLoan.id === loan.id) {
        return false;
      }

      const sameCopy =
        (loan.bookCopyId && otherLoan.bookCopyId && loan.bookCopyId === otherLoan.bookCopyId) ||
        loan.accessionNumber === otherLoan.accessionNumber;

      return sameCopy && (otherLoan.status === "borrowed" || otherLoan.status === "overdue");
    });
  };

  return (
    <div className="max-w-5xl space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900" style={{ fontFamily: "'Playfair Display', serif" }}>
          Loans & Reservations
        </h2>
        <p className="text-gray-400 text-sm mt-0.5">Track the single-copy circulation flow for every book.</p>
      </div>

      <div className="flex gap-2 flex-wrap">
        {STATUS_TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setStatusFilter(tab)}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-full text-sm font-medium capitalize transition-all cursor-pointer whitespace-nowrap ${
              statusFilter === tab
                ? "bg-[#442F73] text-white"
                : "bg-white text-gray-500 border border-gray-200 hover:border-gray-300"
            }`}
          >
            {tab}
            <span
              className={`text-xs font-bold px-1.5 py-0.5 rounded-full ${
                statusFilter === tab ? "bg-white/20 text-white" : "bg-gray-100 text-gray-500"
              }`}
            >
              {counts[tab]}
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
          placeholder="Search by student, email, or book title..."
          className="w-full pl-10 pr-4 py-2.5 text-sm bg-white border border-gray-200 rounded-xl outline-none focus:border-[#442F73] text-gray-800 placeholder-gray-400"
        />
      </div>

      <div className="space-y-3">
        {filtered.map((loan) => (
          <div key={loan.id} className="bg-white rounded-2xl border border-gray-200 p-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="space-y-2 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <p className="font-bold text-gray-900 text-sm">{loan.bookTitle}</p>
                  <span className={`px-2.5 py-0.5 text-xs font-semibold rounded-full capitalize ${statusStyles[loan.status] ?? statusStyles.requested}`}>
                    {loan.status}
                  </span>
                </div>
                <p className="text-gray-500 text-sm">{getBorrowerSummary(loan)}</p>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
                  {loan.borrowerPhone && <span>Phone: {loan.borrowerPhone}</span>}
                  {loan.borrowerStudentId && <span>Student ID: {loan.borrowerStudentId}</span>}
                </div>
                <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-gray-400">
                  <span>Copy: {loan.accessionNumber}</span>
                  <span>Requested: {new Date(loan.requestedAt).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</span>
                  {loan.dueDate && <span>Due: {new Date(loan.dueDate).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</span>}
                  {loan.returnedAt && <span>Returned: {new Date(loan.returnedAt).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}</span>}
                </div>
                {loan.notes && <p className="text-xs text-gray-500 leading-5">{loan.notes}</p>}
              </div>

              <div className="flex flex-wrap gap-2 lg:justify-end">
                {loan.status === "borrowed" && (
                  <>
                    <button
                      onClick={() => markStatus(loan, "returned")}
                      className="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-white text-xs font-semibold rounded-xl cursor-pointer transition-colors whitespace-nowrap"
                    >
                      Mark Returned
                    </button>
                    <button
                      onClick={() => markStatus(loan, "overdue")}
                      className="px-4 py-2 bg-rose-500 hover:bg-rose-600 text-white text-xs font-semibold rounded-xl cursor-pointer transition-colors whitespace-nowrap"
                    >
                      Mark Overdue
                    </button>
                  </>
                )}
                {loan.status === "reserved" && (
                  <>
                    {(() => {
                      const canConfirm = canConfirmReservation(loan);
                      return (
                        <button
                          onClick={() => {
                            if (canConfirm) {
                              markStatus(loan, "borrowed");
                            }
                          }}
                          disabled={!canConfirm}
                          title={canConfirm ? "Confirm this reservation and check out the book." : "You can only confirm this reservation after the current loan has been returned."}
                          className={`px-4 py-2 text-xs font-semibold rounded-xl transition-colors whitespace-nowrap ${
                            canConfirm
                              ? "bg-[#442F73] hover:bg-[#241453] text-white cursor-pointer"
                              : "bg-gray-100 text-gray-400 cursor-not-allowed"
                          }`}
                        >
                          Confirm Reservation
                        </button>
                      );
                    })()}
                    <button
                      onClick={() => markStatus(loan, "cancelled")}
                      className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-semibold rounded-xl cursor-pointer transition-colors whitespace-nowrap"
                    >
                      Cancel Reservation
                    </button>
                  </>
                )}
                {loan.status === "overdue" && (
                  <button
                    onClick={() => markStatus(loan, "returned")}
                    className="px-4 py-2 bg-emerald-500 hover:bg-emerald-600 text-white text-xs font-semibold rounded-xl cursor-pointer transition-colors whitespace-nowrap"
                  >
                    Mark Returned
                  </button>
                )}
                <button
                  onClick={() => deleteLoan(loan.id)}
                  className="px-4 py-2 bg-gray-100 hover:bg-rose-50 text-gray-500 hover:text-rose-600 text-xs font-semibold rounded-xl cursor-pointer transition-colors whitespace-nowrap"
                >
                  Delete
                </button>
              </div>
            </div>
            {loan.status === "reserved" && !canConfirmReservation(loan) && (
              <p className="mt-3 text-xs text-amber-700">
                This reservation can be confirmed only after the current borrower returns the book.
              </p>
            )}
          </div>
        ))}

        {filtered.length === 0 && (
          <div className="bg-white rounded-2xl border border-gray-200 text-center py-16">
            <div className="w-14 h-14 mx-auto bg-gray-50 rounded-full flex items-center justify-center mb-4">
              <i className="ri-bookmark-line text-gray-300 text-2xl" />
            </div>
            <p className="text-gray-500 font-medium mb-1">No circulation records yet</p>
            <p className="text-gray-400 text-sm">Borrowed and reserved books will appear here.</p>
          </div>
        )}
      </div>
    </div>
  );
}
