import { useMemo, useState } from "react";
import { useAdminData } from "../../../hooks/useAdminData";
import type { BookRequest } from "../../../types/library";

const STATUS_TABS = ["all", "pending", "approved", "rejected"] as const;

const statusStyles: Record<string, { badge: string; bg: string }> = {
  pending: {
    badge: "bg-amber-50 text-amber-700 border border-amber-200",
    bg: "bg-amber-50/40",
  },
  approved: {
    badge: "bg-emerald-50 text-emerald-700 border border-emerald-200",
    bg: "bg-emerald-50/30",
  },
  rejected: {
    badge: "bg-red-50 text-red-600 border border-red-200",
    bg: "bg-red-50/20",
  },
};

export default function RequestsInbox() {
  const { requests, updateRequestStatus, deleteRequest } = useAdminData();
  const [statusFilter, setStatusFilter] = useState<typeof STATUS_TABS[number]>("all");
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const getRequestSummary = (request: BookRequest) =>
    [request.studentName, request.studentEmail, request.category].filter(Boolean).join(" · ");

  const getContactSummary = (request: BookRequest) => request.studentPhone || "No phone number provided";

  const counts = useMemo(
    () => ({
      all: requests.length,
      pending: requests.filter((request) => request.status === "pending").length,
      approved: requests.filter((request) => request.status === "approved").length,
      rejected: requests.filter((request) => request.status === "rejected").length,
    }),
    [requests],
  );

  const filtered = useMemo(() => {
    return requests.filter((request) => {
      const matchStatus = statusFilter === "all" || request.status === statusFilter;
      const haystacks = [
        request.bookTitle,
        request.studentName,
        request.studentEmail,
        request.studentPhone ?? "",
        request.category,
      ].map((value) => value.toLowerCase());
      const matchSearch = !search || haystacks.some((value) => value.includes(search.toLowerCase()));
      return matchStatus && matchSearch;
    });
  }, [requests, search, statusFilter]);

  const handleAction = (id: string, status: BookRequest["status"]) => {
    void updateRequestStatus(id, status);
  };

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900" style={{ fontFamily: "'Playfair Display', serif" }}>
          Student Requests
        </h2>
        <p className="text-gray-400 text-sm mt-0.5">Review and manage general library requests from students.</p>
      </div>

      <div className="flex gap-2 flex-wrap">
        {STATUS_TABS.map((status) => (
          <button
            key={status}
            onClick={() => setStatusFilter(status)}
            className={`flex items-center gap-1.5 px-4 py-2 rounded-full text-sm font-medium capitalize transition-all cursor-pointer whitespace-nowrap ${
              statusFilter === status
                ? "bg-[#442F73] text-white"
                : "bg-white text-gray-500 border border-gray-200 hover:border-gray-300"
            }`}
          >
            {status}
            <span
              className={`text-xs font-bold px-1.5 py-0.5 rounded-full ${
                statusFilter === status ? "bg-white/20 text-white" : "bg-gray-100 text-gray-500"
              }`}
            >
              {counts[status]}
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
          placeholder="Search by student, phone number, or book title..."
          className="w-full pl-10 pr-4 py-2.5 text-sm bg-white border border-gray-200 rounded-xl outline-none focus:border-[#442F73] text-gray-800 placeholder-gray-400"
        />
      </div>

      <div className="space-y-3">
        {filtered.map((request) => (
          <div
            key={request.id}
            className={`rounded-2xl border border-gray-200 overflow-hidden transition-all duration-200 ${statusStyles[request.status]?.bg ?? "bg-white"}`}
          >
            <div className="flex items-start gap-4 p-5">
              <div className="w-10 h-10 flex-none bg-[#442F73]/10 rounded-xl flex items-center justify-center">
                <span className="text-sm font-bold text-[#442F73]">
                  {request.studentName
                    .split(" ")
                    .map((name) => name[0])
                    .join("")
                    .slice(0, 2)}
                </span>
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-bold text-gray-900 text-sm">{request.bookTitle}</p>
                    <p className="text-gray-400 text-xs mt-0.5">{getRequestSummary(request)}</p>
                    <p className="text-gray-400 text-xs mt-1">{getContactSummary(request)}</p>
                    {(request.neededFrom || request.neededUntil) && (
                      <div className="flex items-center gap-1.5 mt-1.5">
                        <i className="ri-calendar-2-line text-[#442F73]/50 text-xs" />
                        <span className="text-[10px] text-gray-500 font-medium">
                          {request.neededFrom
                            ? new Date(request.neededFrom).toLocaleDateString("en-GB", {
                                day: "numeric",
                                month: "short",
                                year: "numeric",
                              })
                            : "?"}
                          {" to "}
                          {request.neededUntil
                            ? new Date(request.neededUntil).toLocaleDateString("en-GB", {
                                day: "numeric",
                                month: "short",
                                year: "numeric",
                              })
                            : "?"}
                        </span>
                      </div>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`px-2.5 py-0.5 text-xs font-semibold rounded-full capitalize ${statusStyles[request.status]?.badge}`}>
                      {request.status}
                    </span>
                    <span className="text-xs text-gray-400">
                      {new Date(request.submittedAt).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}
                    </span>
                  </div>
                </div>

                <button
                  onClick={() => setExpanded(expanded === request.id ? null : request.id)}
                  className="mt-2 text-xs text-[#442F73] hover:underline cursor-pointer flex items-center gap-1"
                >
                  {expanded === request.id ? "Hide details" : "View details"}
                  <i className={`ri-arrow-${expanded === request.id ? "up" : "down"}-s-line`} />
                </button>

                {expanded === request.id && (
                  <div className="mt-3 space-y-2">
                    {(request.neededFrom || request.neededUntil) && (
                      <div className="flex items-center gap-2 bg-[#442F73]/5 border border-[#442F73]/12 rounded-xl px-3 py-2.5">
                        <i className="ri-calendar-line text-[#442F73] text-sm flex-none" />
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <span className="text-xs font-semibold text-[#442F73]">Needed period:</span>
                          <span className="text-xs text-gray-600 font-medium">
                            {request.neededFrom
                              ? new Date(request.neededFrom).toLocaleDateString("en-GB", {
                                  day: "numeric",
                                  month: "short",
                                  year: "numeric",
                                })
                              : "-"}
                          </span>
                          <i className="ri-arrow-right-line text-gray-400 text-xs" />
                          <span className="text-xs text-gray-600 font-medium">
                            {request.neededUntil
                              ? new Date(request.neededUntil).toLocaleDateString("en-GB", {
                                  day: "numeric",
                                  month: "short",
                                  year: "numeric",
                                })
                              : "-"}
                          </span>
                        </div>
                      </div>
                    )}
                    <div className="bg-white/70 rounded-xl p-3 border border-gray-100">
                      <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1">Student Contact</p>
                      <p className="text-gray-500 text-xs leading-relaxed">{getContactSummary(request)}</p>
                    </div>
                    <div className="bg-white/70 rounded-xl p-3 border border-gray-100">
                      <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wide mb-1">Reason</p>
                      <p className="text-gray-500 text-xs leading-relaxed italic">"{request.reason}"</p>
                    </div>
                  </div>
                )}
              </div>
            </div>

            {request.status === "pending" && (
              <div className="flex items-center gap-2 px-5 py-3 border-t border-gray-100 bg-white/50">
                <button
                  onClick={() => handleAction(request.id, "approved")}
                  className="flex items-center gap-1.5 px-4 py-1.5 bg-emerald-500 hover:bg-emerald-600 text-white text-xs font-semibold rounded-lg cursor-pointer transition-colors whitespace-nowrap"
                >
                  <i className="ri-check-line" />
                  Approve
                </button>
                <button
                  onClick={() => handleAction(request.id, "rejected")}
                  className="flex items-center gap-1.5 px-4 py-1.5 bg-gray-100 hover:bg-red-50 text-gray-600 hover:text-red-600 text-xs font-semibold rounded-lg cursor-pointer transition-colors whitespace-nowrap"
                >
                  <i className="ri-close-line" />
                  Reject
                </button>
                <button
                  onClick={() => deleteRequest(request.id)}
                  className="ml-auto flex items-center gap-1 text-xs text-gray-300 hover:text-red-400 cursor-pointer transition-colors"
                >
                  <i className="ri-delete-bin-line" />
                  Delete
                </button>
              </div>
            )}
            {request.status !== "pending" && (
              <div className="flex items-center justify-between px-5 py-2.5 border-t border-gray-100 bg-white/40">
                <span className="text-xs text-gray-400 capitalize">Marked as {request.status}</span>
                <div className="flex gap-2">
                  {request.status === "approved" && (
                    <button
                      onClick={() => handleAction(request.id, "rejected")}
                      className="text-xs text-gray-400 hover:text-red-500 cursor-pointer transition-colors"
                    >
                      Undo
                    </button>
                  )}
                  {request.status === "rejected" && (
                    <button
                      onClick={() => handleAction(request.id, "approved")}
                      className="text-xs text-gray-400 hover:text-emerald-600 cursor-pointer transition-colors"
                    >
                      Approve instead
                    </button>
                  )}
                  <button
                    onClick={() => deleteRequest(request.id)}
                    className="text-xs text-gray-300 hover:text-red-400 cursor-pointer transition-colors"
                  >
                    <i className="ri-delete-bin-line" />
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}

        {filtered.length === 0 && (
          <div className="bg-white rounded-2xl border border-gray-200 text-center py-16">
            <div className="w-14 h-14 mx-auto bg-gray-50 rounded-full flex items-center justify-center mb-4">
              <i className="ri-inbox-2-line text-gray-300 text-2xl" />
            </div>
            <p className="text-gray-500 font-medium mb-1">No requests found</p>
            <p className="text-gray-400 text-sm">Requests from students will appear here.</p>
          </div>
        )}
      </div>
    </div>
  );
}
