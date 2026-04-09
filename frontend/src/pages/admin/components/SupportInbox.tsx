import { useMemo, useState } from "react";
import { useAdminData } from "../../../hooks/useAdminData";
import type { SupportMessage } from "../../../types/library";

const STATUS_TABS = ["all", "new", "in_progress", "resolved"] as const;

const statusStyles: Record<SupportMessage["status"], string> = {
  new: "bg-amber-50 text-amber-700 border border-amber-200",
  in_progress: "bg-sky-50 text-sky-700 border border-sky-200",
  resolved: "bg-emerald-50 text-emerald-700 border border-emerald-200",
};

export default function SupportInbox() {
  const { supportMessages, updateSupportMessage, deleteSupportMessage } = useAdminData();
  const [statusFilter, setStatusFilter] = useState<typeof STATUS_TABS[number]>("all");
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const counts = useMemo(
    () => ({
      all: supportMessages.length,
      new: supportMessages.filter((message) => message.status === "new").length,
      in_progress: supportMessages.filter((message) => message.status === "in_progress").length,
      resolved: supportMessages.filter((message) => message.status === "resolved").length,
    }),
    [supportMessages],
  );

  const filtered = useMemo(
    () =>
      supportMessages.filter((message) => {
        const matchStatus = statusFilter === "all" || message.status === statusFilter;
        const haystacks = [message.fullName, message.email, message.course ?? "", message.subject, message.message].map(
          (value) => value.toLowerCase(),
        );
        const matchSearch = !search || haystacks.some((value) => value.includes(search.toLowerCase()));
        return matchStatus && matchSearch;
      }),
    [search, statusFilter, supportMessages],
  );

  const handleStatus = (id: string, status: SupportMessage["status"]) => {
    void updateSupportMessage(id, { status });
  };

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h2 className="text-xl font-bold text-gray-900" style={{ fontFamily: "'Playfair Display', serif" }}>
          Support Inbox
        </h2>
        <p className="text-gray-400 text-sm mt-0.5">Messages submitted from the public Support page.</p>
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
            {status === "in_progress" ? "In Progress" : status}
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
          placeholder="Search by name, email, subject, or course..."
          className="w-full pl-10 pr-4 py-2.5 text-sm bg-white border border-gray-200 rounded-xl outline-none focus:border-[#442F73] text-gray-800 placeholder-gray-400"
        />
      </div>

      <div className="space-y-3">
        {filtered.map((message) => (
          <div key={message.id} className="rounded-2xl border border-gray-200 bg-white overflow-hidden">
            <div className="p-5">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-bold text-sm text-gray-900">{message.subject}</p>
                  <p className="mt-0.5 text-xs text-gray-400">
                    {[message.fullName, message.email, message.course].filter(Boolean).join(" · ")}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className={`px-2.5 py-0.5 text-xs font-semibold rounded-full capitalize ${statusStyles[message.status]}`}>
                    {message.status === "in_progress" ? "In Progress" : message.status}
                  </span>
                  <span className="text-xs text-gray-400">
                    {new Date(message.submittedAt).toLocaleDateString("en-GB", { day: "numeric", month: "short" })}
                  </span>
                </div>
              </div>

              <button
                onClick={() => setExpanded(expanded === message.id ? null : message.id)}
                className="mt-2 text-xs text-[#442F73] hover:underline cursor-pointer flex items-center gap-1"
              >
                {expanded === message.id ? "Hide message" : "View message"}
                <i className={`ri-arrow-${expanded === message.id ? "up" : "down"}-s-line`} />
              </button>

              {expanded === message.id && (
                <div className="mt-3 rounded-xl border border-gray-100 bg-gray-50 p-4">
                  <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400 mb-1">Message</p>
                  <p className="text-sm leading-6 text-gray-600 whitespace-pre-line">{message.message}</p>
                </div>
              )}
            </div>

            <div className="flex items-center gap-2 px-5 py-3 border-t border-gray-100 bg-white">
              {message.status !== "new" && (
                <button
                  onClick={() => handleStatus(message.id, "new")}
                  className="px-3 py-1.5 rounded-lg bg-gray-100 text-gray-600 text-xs font-semibold cursor-pointer"
                >
                  Mark New
                </button>
              )}
              {message.status !== "in_progress" && (
                <button
                  onClick={() => handleStatus(message.id, "in_progress")}
                  className="px-3 py-1.5 rounded-lg bg-sky-500 text-white text-xs font-semibold cursor-pointer"
                >
                  Mark In Progress
                </button>
              )}
              {message.status !== "resolved" && (
                <button
                  onClick={() => handleStatus(message.id, "resolved")}
                  className="px-3 py-1.5 rounded-lg bg-emerald-500 text-white text-xs font-semibold cursor-pointer"
                >
                  Mark Resolved
                </button>
              )}
              <button
                onClick={() => deleteSupportMessage(message.id)}
                className="ml-auto text-xs text-gray-300 hover:text-red-400 cursor-pointer transition-colors"
              >
                <i className="ri-delete-bin-line" />
              </button>
            </div>
          </div>
        ))}

        {filtered.length === 0 && (
          <div className="bg-white rounded-2xl border border-gray-200 text-center py-16">
            <div className="w-14 h-14 mx-auto bg-gray-50 rounded-full flex items-center justify-center mb-4">
              <i className="ri-mail-open-line text-gray-300 text-2xl" />
            </div>
            <p className="text-gray-500 font-medium mb-1">No support messages found</p>
            <p className="text-gray-400 text-sm">Messages from the Support page will appear here.</p>
          </div>
        )}
      </div>
    </div>
  );
}
