import { useState, useEffect } from "react";
import { useAdminData } from "../../../hooks/useAdminData";
import type { Resource } from "../../../types/library";

interface Props {
  book: Resource | null;
  onClose: () => void;
}

const empty: Omit<Resource, "id"> = {
  title: "",
  author: "",
  category: "Branding & Advertising",
  categoryId: "branding-advertising",
};

export default function BookFormModal({ book, onClose }: Props) {
  const { addBook, updateBook, categories } = useAdminData();
  const categoryNames = categories.map((category) => category.name);
  const [form, setForm] = useState<Omit<Resource, "id">>(book ? { ...book } : { ...empty });
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setForm(book ? { ...book } : { ...empty });
    setSaved(false);
  }, [book]);

  const isEdit = !!book;

  const handleSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (isEdit && book) {
      updateBook(book.id, form);
    } else {
      addBook(form);
    }
    setSaved(true);
    setTimeout(() => onClose(), 900);
  };

  const set = <K extends keyof typeof form>(key: K, val: (typeof form)[K]) =>
    setForm((prev) => ({ ...prev, [key]: val }));

  const handleCategoryChange = (value: string) => {
    const categoryId = categories.find((category) => category.name === value)?.slug ?? "";

    setForm((prev) => ({ ...prev, category: value, categoryId }));
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="bg-white rounded-2xl w-full max-w-xl shadow-2xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between p-6 border-b border-gray-100 flex-none">
          <div>
            <h2 className="font-bold text-gray-900 text-lg" style={{ fontFamily: "'Playfair Display', serif" }}>
              {isEdit ? "Edit Book" : "Add New Book"}
            </h2>
            <p className="text-gray-400 text-xs mt-0.5">Only real library fields are stored here.</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-100 cursor-pointer">
            <i className="ri-close-line text-gray-500" />
          </button>
        </div>

        <form id="book-form-modal" onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6 space-y-5">
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1.5">Book Title</label>
            <input
              required
              type="text"
              value={form.title}
              onChange={(e) => set("title", e.target.value)}
              className="w-full px-4 py-2.5 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1.5">Author</label>
            <input
              required
              type="text"
              value={form.author}
              onChange={(e) => set("author", e.target.value)}
              className="w-full px-4 py-2.5 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1.5">Category</label>
            <select
              value={form.category}
              onChange={(e) => handleCategoryChange(e.target.value)}
              className="w-full px-3 py-2.5 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] bg-white text-gray-800 cursor-pointer"
            >
              {categoryNames.map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
        </form>

        <div className="flex items-center justify-end gap-3 p-6 border-t border-gray-100 flex-none">
          <button
            type="button"
            onClick={onClose}
            className="px-5 py-2.5 text-sm font-semibold text-gray-600 bg-gray-100 hover:bg-gray-200 rounded-xl cursor-pointer transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            form="book-form-modal"
            disabled={saved}
            className={`flex items-center gap-2 px-6 py-2.5 text-sm font-semibold rounded-xl cursor-pointer transition-all ${
              saved ? "bg-emerald-500 text-white" : "bg-[#442F73] hover:bg-[#241453] text-white"
            }`}
          >
            <i className={saved ? "ri-check-line" : "ri-save-line"} />
            {saved ? "Saved!" : isEdit ? "Save Changes" : "Add Book"}
          </button>
        </div>
      </div>
    </div>
  );
}
