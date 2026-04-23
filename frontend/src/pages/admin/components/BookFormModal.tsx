import { useEffect, useState } from "react";
import { useAdminData } from "../../../hooks/useAdminData";
import type { Resource } from "../../../types/library";

interface Props {
  book: Resource | null;
  onClose: () => void;
}

type BookFormState = {
  title: string;
  author: string;
  category: string;
  categoryId: string;
  type: NonNullable<Resource["type"]>;
  level: string;
  publisher: string;
  edition: string;
  publicationYear: string;
  pageCount: string;
  isbn13: string;
  isbn10: string;
  coverImage: string;
  infoLink: string;
  description: string;
  dateAdded: string;
  coverColor: string;
  inventoryCount: number;
};

type BookFormSection = "basics" | "catalog" | "display" | "system";

const RESOURCE_TYPES: Array<NonNullable<Resource["type"]>> = ["Book", "Article", "Guide", "Journal", "Video", "Template"];

const BOOK_FORM_SECTIONS: Array<{
  id: BookFormSection;
  label: string;
  description: string;
}> = [
  { id: "basics", label: "Basics", description: "Title, author, category, type, and description." },
  { id: "catalog", label: "Catalog", description: "Publisher, edition, year, ISBN, and copies." },
  { id: "display", label: "Display", description: "Cover, color, link, and spotlight flags." },
  { id: "system", label: "System", description: "Availability and circulation metrics." },
];

function flattenStructuredError(value: unknown): string | null {
  if (typeof value === "string") {
    return value;
  }
  if (Array.isArray(value)) {
    const firstString = value.find((item) => typeof item === "string");
    return typeof firstString === "string" ? firstString : null;
  }
  if (value && typeof value === "object") {
    for (const nestedValue of Object.values(value)) {
      const nestedMessage = flattenStructuredError(nestedValue);
      if (nestedMessage) {
        return nestedMessage;
      }
    }
  }
  return null;
}

function formatSaveError(message: string) {
  const trimmed = message.trim();
  if (trimmed.startsWith("{")) {
    try {
      const parsed = JSON.parse(trimmed) as unknown;
      const nested = flattenStructuredError(parsed);
      if (nested) {
        return nested;
      }
    } catch {
      // Fall through to the raw message.
    }
  }
  return trimmed || "This book could not be saved right now.";
}

function buildFormState(book: Resource | null): BookFormState {
  if (!book) {
    return { ...empty };
  }

  return {
    title: book.title,
    author: book.author,
    category: book.category,
    categoryId: book.categoryId,
    type: book.type ?? "Book",
    level: book.level ?? "",
    publisher: book.publisher ?? "",
    edition: book.edition ?? "",
    publicationYear: book.publicationYear ?? "",
    pageCount: book.pageCount != null ? String(book.pageCount) : "",
    isbn13: book.isbn13 ?? "",
    isbn10: book.isbn10 ?? "",
    coverImage: book.coverImage ?? "",
    infoLink: book.infoLink ?? "",
    description: book.description ?? "",
    dateAdded: book.dateAdded ?? "",
    coverColor: book.coverColor ?? "#442F73",
    inventoryCount: book.totalCopies ?? book.inventoryCount ?? empty.inventoryCount,
  };
}

function buildPayload(form: BookFormState) {
  return {
    title: form.title.trim(),
    author: form.author.trim(),
    category: form.category,
    categoryId: form.categoryId,
    type: form.type,
    level: form.level.trim(),
    publisher: form.publisher.trim(),
    edition: form.edition.trim(),
    publicationYear: form.publicationYear.trim(),
    pageCount: form.pageCount.trim() ? Number(form.pageCount) : undefined,
    isbn13: form.isbn13.trim(),
    isbn10: form.isbn10.trim(),
    coverImage: form.coverImage.trim(),
    infoLink: form.infoLink.trim(),
    description: form.description.trim(),
    dateAdded: form.dateAdded || undefined,
    coverColor: form.coverColor || "#442F73",
    inventoryCount: form.inventoryCount,
  };
}

const empty: BookFormState = {
  title: "",
  author: "",
  category: "Branding & Advertising",
  categoryId: "branding-advertising",
  type: "Book",
  level: "",
  publisher: "",
  edition: "",
  publicationYear: "",
  pageCount: "",
  isbn13: "",
  isbn10: "",
  coverImage: "",
  infoLink: "",
  description: "",
  dateAdded: "",
  coverColor: "#442F73",
  inventoryCount: 3,
};

function MetricTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-[#E9D9BD] bg-[#FCFAF6] px-3 py-3">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">{label}</p>
      <p className="mt-1 text-sm font-semibold text-[#241453]">{value}</p>
    </div>
  );
}

export default function BookFormModal({ book, onClose }: Props) {
  const { addBook, updateBook, categories } = useAdminData();
  const categoryNames = categories.map((category) => category.name);
  const [form, setForm] = useState<BookFormState>(buildFormState(book));
  const [activeSection, setActiveSection] = useState<BookFormSection>("basics");
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  useEffect(() => {
    setForm(buildFormState(book));
    setActiveSection("basics");
    setSaved(false);
    setSaving(false);
    setSaveError("");
  }, [book]);

  const isEdit = !!book;

  const visibleSections = isEdit
    ? BOOK_FORM_SECTIONS
    : BOOK_FORM_SECTIONS.filter((section) => section.id !== "system");

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (saving) return;

    setSaving(true);
    setSaveError("");

    try {
      const payload = buildPayload(form);
      if (isEdit && book) {
        await updateBook(book.id, payload);
      } else {
        await addBook(payload);
      }
      setSaved(true);
      setTimeout(() => onClose(), 900);
    } catch (error) {
      const rawMessage = error instanceof Error ? error.message : "This book could not be saved right now.";
      setSaveError(formatSaveError(rawMessage));
    } finally {
      setSaving(false);
    }
  };

  const set = <K extends keyof BookFormState>(key: K, val: BookFormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: val }));

  const handleCategoryChange = (value: string) => {
    const categoryId = categories.find((category) => category.name === value)?.slug ?? "";
    setForm((prev) => ({ ...prev, category: value, categoryId }));
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/50 p-4 backdrop-blur-sm sm:p-6">
      <div className="flex min-h-full items-start justify-center">
        <div className="flex h-[calc(100vh-2rem)] w-full max-w-5xl flex-col overflow-hidden rounded-[28px] bg-white shadow-2xl sm:h-[calc(100vh-4rem)] sm:max-h-[920px]">
        <div className="flex shrink-0 items-center justify-between border-b border-gray-100 px-6 py-5">
          <div>
            <h2 className="text-lg font-bold text-gray-900" style={{ fontFamily: "'Playfair Display', serif" }}>
              {isEdit ? "Edit Resource" : "Add New Resource"}
            </h2>
            <p className="mt-0.5 text-xs text-gray-400">
              Admins can manage full resource metadata here. Availability metrics stay system-managed.
            </p>
          </div>
          <button onClick={onClose} className="flex h-8 w-8 items-center justify-center rounded-lg hover:bg-gray-100 cursor-pointer">
            <i className="ri-close-line text-gray-500" />
          </button>
        </div>

        <form id="book-form-modal" onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="shrink-0 border-b border-gray-100 bg-white px-6 py-4">
                {saveError && (
                  <div className="mb-4 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                    {saveError}
                  </div>
                )}

                <div className="rounded-[24px] border border-gray-200 bg-[#FCFAF6] p-3 shadow-sm">
                  <div className="flex flex-wrap gap-2">
                    {visibleSections.map((section) => (
                      <button
                        key={section.id}
                        type="button"
                        onClick={() => setActiveSection(section.id)}
                        className={`rounded-xl px-3 py-2 text-sm font-semibold transition-colors ${
                          activeSection === section.id
                            ? "bg-[#442F73] text-white shadow-sm"
                            : "bg-white text-gray-600 hover:text-[#442F73]"
                        }`}
                      >
                        {section.label}
                      </button>
                    ))}
                  </div>
                  <p className="mt-3 px-1 text-xs leading-5 text-gray-400">
                    {visibleSections.find((section) => section.id === activeSection)?.description}
                  </p>
                </div>
              </div>

              <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-6 py-5">
                <div className="mx-auto max-w-4xl space-y-6 pb-2">
              {activeSection === "basics" && (
                <section className="space-y-5 rounded-[24px] border border-gray-100 bg-white p-5 shadow-sm sm:p-6">
                <div>
                  <h3 className="text-sm font-semibold text-[#241453]">Core Details</h3>
                  <p className="mt-1 text-xs text-gray-400">These fields drive the main listing and detail page.</p>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="md:col-span-2">
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">Title</label>
                    <input
                      required
                      type="text"
                      value={form.title}
                      onChange={(e) => set("title", e.target.value)}
                      className="w-full rounded-xl border border-gray-200 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10"
                    />
                  </div>

                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">Author</label>
                    <input
                      required
                      type="text"
                      value={form.author}
                      onChange={(e) => set("author", e.target.value)}
                      className="w-full rounded-xl border border-gray-200 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10"
                    />
                  </div>

                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">Category</label>
                    <select
                      value={form.category}
                      onChange={(e) => handleCategoryChange(e.target.value)}
                      className="w-full cursor-pointer rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm text-gray-800 outline-none focus:border-[#442F73]"
                    >
                      {categoryNames.map((category) => (
                        <option key={category}>{category}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">Type</label>
                    <select
                      value={form.type}
                      onChange={(e) => set("type", e.target.value as NonNullable<Resource["type"]>)}
                      className="w-full cursor-pointer rounded-xl border border-gray-200 bg-white px-3 py-2.5 text-sm text-gray-800 outline-none focus:border-[#442F73]"
                    >
                      {RESOURCE_TYPES.map((type) => (
                        <option key={type} value={type}>{type}</option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">Level</label>
                    <input
                      type="text"
                      value={form.level}
                      onChange={(e) => set("level", e.target.value)}
                      placeholder="Optional audience or level"
                      className="w-full rounded-xl border border-gray-200 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10"
                    />
                  </div>

                  <div className="md:col-span-2">
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">Description</label>
                    <textarea
                      rows={7}
                      value={form.description}
                      onChange={(e) => set("description", e.target.value)}
                      placeholder="Short description shown on the public detail page"
                      className="min-h-[180px] w-full resize-y rounded-xl border border-gray-200 px-4 py-3 text-sm text-gray-800 outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10"
                    />
                  </div>
                </div>
                </section>
              )}

              {activeSection === "catalog" && (
                <section className="space-y-5 rounded-[24px] border border-gray-100 bg-white p-5 shadow-sm sm:p-6">
                <div>
                  <h3 className="text-sm font-semibold text-[#241453]">Publishing & Cataloguing</h3>
                  <p className="mt-1 text-xs text-gray-400">These values appear in the book information section.</p>
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">Publisher</label>
                    <input
                      type="text"
                      value={form.publisher}
                      onChange={(e) => set("publisher", e.target.value)}
                      className="w-full rounded-xl border border-gray-200 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10"
                    />
                  </div>

                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">Edition</label>
                    <input
                      type="text"
                      value={form.edition}
                      onChange={(e) => set("edition", e.target.value)}
                      placeholder="e.g. 2nd Edition"
                      className="w-full rounded-xl border border-gray-200 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10"
                    />
                  </div>

                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">Publication Year</label>
                    <input
                      type="text"
                      maxLength={4}
                      value={form.publicationYear}
                      onChange={(e) => set("publicationYear", e.target.value.replace(/[^\d]/g, "").slice(0, 4))}
                      placeholder="YYYY"
                      className="w-full rounded-xl border border-gray-200 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10"
                    />
                  </div>

                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">Page Count</label>
                    <input
                      type="number"
                      min={1}
                      value={form.pageCount}
                      onChange={(e) => set("pageCount", e.target.value)}
                      className="w-full rounded-xl border border-gray-200 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10"
                    />
                  </div>

                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">ISBN-13</label>
                    <input
                      type="text"
                      maxLength={13}
                      value={form.isbn13}
                      onChange={(e) => set("isbn13", e.target.value.replace(/[^0-9Xx-]/g, ""))}
                      className="w-full rounded-xl border border-gray-200 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10"
                    />
                  </div>

                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">ISBN-10</label>
                    <input
                      type="text"
                      maxLength={10}
                      value={form.isbn10}
                      onChange={(e) => set("isbn10", e.target.value.replace(/[^0-9Xx-]/g, ""))}
                      className="w-full rounded-xl border border-gray-200 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10"
                    />
                  </div>

                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">Date Added</label>
                    <input
                      type="date"
                      value={form.dateAdded}
                      onChange={(e) => set("dateAdded", e.target.value)}
                      className="w-full rounded-xl border border-gray-200 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10"
                    />
                  </div>

                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">Total Copies</label>
                    <input
                      required
                      min={1}
                      type="number"
                      value={form.inventoryCount}
                      onChange={(e) => {
                        const nextValue = Number(e.target.value);
                        set("inventoryCount", Number.isNaN(nextValue) ? 1 : Math.max(1, nextValue));
                      }}
                      className="w-full rounded-xl border border-gray-200 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10"
                    />
                  </div>
                </div>
                </section>
              )}

              {activeSection === "display" && (
                <section className="space-y-5 rounded-[24px] border border-gray-100 bg-white p-5 shadow-sm sm:p-6">
                <div>
                  <h3 className="text-sm font-semibold text-[#241453]">Media & Display</h3>
                  <p className="mt-1 text-xs text-gray-400">These fields shape the public card and detail page appearance.</p>
                </div>

                <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_120px]">
                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">Book Cover Image</label>
                    <input
                      type="url"
                      value={form.coverImage}
                      onChange={(e) => set("coverImage", e.target.value)}
                      placeholder="https://..."
                      className="w-full rounded-xl border border-gray-200 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10"
                    />
                  </div>

                  <div>
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">Accent Color</label>
                    <div className="flex items-center gap-3 rounded-xl border border-gray-200 px-3 py-2.5">
                      <input
                        type="color"
                        value={form.coverColor}
                        onChange={(e) => set("coverColor", e.target.value)}
                        className="h-9 w-12 cursor-pointer rounded border-0 bg-transparent p-0"
                      />
                      <span className="text-xs font-medium text-gray-500">{form.coverColor}</span>
                    </div>
                  </div>

                  <div className="md:col-span-2">
                    <label className="mb-1.5 block text-xs font-semibold text-gray-600">External Book Page Link</label>
                    <input
                      type="url"
                      value={form.infoLink}
                      onChange={(e) => set("infoLink", e.target.value)}
                      placeholder="Optional external reference link"
                      className="w-full rounded-xl border border-gray-200 px-4 py-2.5 text-sm text-gray-800 outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10"
                    />
                  </div>
                </div>
                </section>
              )}

              {activeSection === "system" && isEdit && book && (
                <section className="space-y-5 rounded-[24px] border border-gray-100 bg-white p-5 shadow-sm sm:p-6">
                  <div>
                    <h3 className="text-sm font-semibold text-[#241453]">System Managed</h3>
                    <p className="mt-1 text-xs leading-5 text-gray-400">
                      These values come from copies, requests, and loan activity. They update automatically across the library.
                    </p>
                  </div>

                  <div className="grid gap-3 sm:grid-cols-2">
                    <MetricTile label="Availability" value={book.availabilityLabel ?? "Unavailable"} />
                    <MetricTile label="Status" value={book.availabilityStatus ?? "Unavailable"} />
                    <MetricTile label="Total Copies" value={book.totalCopies ?? 0} />
                    <MetricTile label="Available Copies" value={book.availableCopies ?? 0} />
                    <MetricTile label="Borrowable" value={book.borrowableCopies ?? 0} />
                    <MetricTile label="Pending Requests" value={book.pendingBorrowRequests ?? 0} />
                  </div>

                  {book.expectedAvailableDate && (
                    <div className="rounded-xl border border-gray-200 bg-[#FCFAF6] px-4 py-3">
                      <p className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">Expected Available</p>
                      <p className="mt-1 text-sm font-semibold text-[#241453]">{book.expectedAvailableDate}</p>
                    </div>
                  )}
                </section>
              )}
                </div>
              </div>
            </div>
          </div>
        </form>

        <div className="flex shrink-0 items-center justify-end gap-3 border-t border-gray-100 bg-white px-6 py-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl bg-gray-100 px-5 py-2.5 text-sm font-semibold text-gray-600 transition-colors hover:bg-gray-200 cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="submit"
            form="book-form-modal"
            disabled={saved || saving}
            className={`flex items-center gap-2 rounded-xl px-6 py-2.5 text-sm font-semibold text-white transition-all cursor-pointer ${
              saved ? "bg-emerald-500" : "bg-[#442F73] hover:bg-[#241453]"
            }`}
          >
            <i className={saved ? "ri-check-line" : saving ? "ri-loader-4-line animate-spin" : "ri-save-line"} />
            {saved ? "Saved!" : saving ? "Saving..." : isEdit ? "Save Changes" : "Add Resource"}
          </button>
        </div>
      </div>
      </div>
    </div>
  );
}
