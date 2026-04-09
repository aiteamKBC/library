import { useEffect, useState } from "react";
import { useAdminData } from "../../../hooks/useAdminData";

interface Props {
  onClose: () => void;
}

const DEFAULT_COLOR = "#442F73";
const DEFAULT_ICON = "ri-book-open-line";

export default function CategoryFormModal({ onClose }: Props) {
  const { addCategory } = useAdminData();
  const [form, setForm] = useState({
    name: "",
    description: "",
    color: DEFAULT_COLOR,
    icon: DEFAULT_ICON,
  });
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setSaved(false);
  }, []);

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    await addCategory(form);
    setSaved(true);
    setTimeout(() => onClose(), 900);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
      <div className="bg-white rounded-2xl w-full max-w-xl shadow-2xl max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between p-6 border-b border-gray-100 flex-none">
          <div>
            <h2 className="font-bold text-gray-900 text-lg" style={{ fontFamily: "'Playfair Display', serif" }}>
              Add New Category
            </h2>
            <p className="text-gray-400 text-xs mt-0.5">Create a category for books that need a clear place in the library.</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-100 cursor-pointer">
            <i className="ri-close-line text-gray-500" />
          </button>
        </div>

        <form id="category-form-modal" onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-6 space-y-5">
          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1.5">Category Name</label>
            <input
              required
              type="text"
              value={form.name}
              onChange={(e) => setForm((prev) => ({ ...prev, name: e.target.value }))}
              placeholder="e.g. General"
              className="w-full px-4 py-2.5 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-600 mb-1.5">Description</label>
            <textarea
              rows={3}
              value={form.description}
              onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
              placeholder="Optional short description for this category"
              className="w-full px-4 py-2.5 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800 resize-none"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1.5">Badge Colour</label>
              <input
                type="color"
                value={form.color}
                onChange={(e) => setForm((prev) => ({ ...prev, color: e.target.value }))}
                className="w-full h-11 px-2 py-2 border border-gray-200 rounded-xl bg-white cursor-pointer"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-gray-600 mb-1.5">Icon Class</label>
              <input
                type="text"
                value={form.icon}
                onChange={(e) => setForm((prev) => ({ ...prev, icon: e.target.value }))}
                placeholder="ri-book-open-line"
                className="w-full px-4 py-2.5 text-sm border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800"
              />
            </div>
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
            form="category-form-modal"
            disabled={saved}
            className={`flex items-center gap-2 px-6 py-2.5 text-sm font-semibold rounded-xl cursor-pointer transition-all ${
              saved ? "bg-emerald-500 text-white" : "bg-[#442F73] hover:bg-[#241453] text-white"
            }`}
          >
            <i className={saved ? "ri-check-line" : "ri-save-line"} />
            {saved ? "Saved!" : "Add Category"}
          </button>
        </div>
      </div>
    </div>
  );
}
