import { useState, useMemo } from "react";
import { useAdminData } from "../../../hooks/useAdminData";
import BookFormModal from "./BookFormModal";
import CategoryFormModal from "./CategoryFormModal";
import type { Resource } from "../../../types/library";

export default function BooksManager() {
  const { books, deleteBook, categories: dbCategories } = useAdminData();
  const categoryColorMap = Object.fromEntries(dbCategories.map((category) => [category.name, category.color]));
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("All");
  const [modalOpen, setModalOpen] = useState(false);
  const [categoryModalOpen, setCategoryModalOpen] = useState(false);
  const [editingBook, setEditingBook] = useState<Resource | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const categories = useMemo(() => {
    const cats = [...new Set(books.map((b) => b.category))];
    return ["All", ...cats];
  }, [books]);

  const filtered = useMemo(() => {
    return books.filter((b) => {
      const matchSearch =
        !search ||
        b.title.toLowerCase().includes(search.toLowerCase()) ||
        b.author.toLowerCase().includes(search.toLowerCase());
      const matchCat = categoryFilter === "All" || b.category === categoryFilter;
      return matchSearch && matchCat;
    });
  }, [books, search, categoryFilter]);

  return (
    <div className="max-w-7xl space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-gray-900" style={{ fontFamily: "'Playfair Display', serif" }}>Books</h2>
          <p className="text-gray-400 text-sm mt-0.5">{books.length} books in the library</p>
        </div>
        <div className="flex flex-col sm:flex-row gap-3">
          <button
            onClick={() => setCategoryModalOpen(true)}
            className="flex items-center justify-center gap-2 px-5 py-2.5 bg-white border border-[#442F73]/20 hover:border-[#442F73] text-[#442F73] text-sm font-semibold rounded-xl transition-colors duration-200 cursor-pointer whitespace-nowrap"
          >
            <i className="ri-price-tag-3-line" />
            Add New Category
          </button>
          <button
            onClick={() => { setEditingBook(null); setModalOpen(true); }}
            className="flex items-center justify-center gap-2 px-5 py-2.5 bg-[#442F73] hover:bg-[#241453] text-white text-sm font-semibold rounded-xl transition-colors duration-200 cursor-pointer whitespace-nowrap"
          >
            <i className="ri-add-line" />
            Add New Book
          </button>
        </div>
      </div>

      <div className="bg-white rounded-2xl border border-gray-200 p-4 flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <i className="ri-search-line absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by title or author..."
            className="w-full pl-9 pr-4 py-2.5 text-sm bg-gray-50 border border-gray-200 rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800 placeholder-gray-400"
          />
        </div>
        <select
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
          className="px-4 py-2.5 text-sm bg-gray-50 border border-gray-200 rounded-xl outline-none focus:border-[#442F73] text-gray-700 cursor-pointer min-w-[160px]"
        >
          {categories.map((c) => <option key={c}>{c}</option>)}
        </select>
      </div>

      <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/60">
                <th className="text-left px-5 py-3.5 text-xs font-semibold text-gray-500 uppercase tracking-wide">Book</th>
                <th className="text-left px-4 py-3.5 text-xs font-semibold text-gray-500 uppercase tracking-wide hidden md:table-cell">Category</th>
                <th className="px-4 py-3.5" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {filtered.map((book) => {
                const color = categoryColorMap[book.category] ?? "#442F73";

                return (
                  <tr key={book.id} className="hover:bg-gray-50/60 transition-colors">
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-3">
                        <div
                          className="w-9 h-9 flex-none rounded-lg flex items-center justify-center"
                          style={{ backgroundColor: `${color}20` }}
                        >
                          <i className="ri-book-2-line text-sm" style={{ color }} />
                        </div>
                        <div>
                          <p className="font-semibold text-gray-900 text-sm line-clamp-1">{book.title}</p>
                          <p className="text-gray-400 text-xs">by {book.author}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-4 hidden md:table-cell">
                      <span className="text-xs px-2 py-0.5 rounded-full font-medium" style={{ backgroundColor: `${color}12`, color }}>
                        {book.category}
                      </span>
                    </td>
                    <td className="px-4 py-4">
                      <div className="flex items-center gap-1 justify-end">
                        <button
                          onClick={() => { setEditingBook(book); setModalOpen(true); }}
                          className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-[#442F73] hover:bg-[#F3E9DA] transition-all cursor-pointer"
                        >
                          <i className="ri-edit-line text-sm" />
                        </button>
                        <button
                          onClick={() => setConfirmDelete(book.id)}
                          className="w-8 h-8 flex items-center justify-center rounded-lg text-gray-400 hover:text-rose-600 hover:bg-rose-50 transition-all cursor-pointer"
                        >
                          <i className="ri-delete-bin-line text-sm" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {filtered.length === 0 && (
            <div className="text-center py-14">
              <i className="ri-search-line text-3xl text-gray-300 block mb-2" />
              <p className="text-gray-400 text-sm">No books match your search</p>
            </div>
          )}
        </div>
      </div>

      {confirmDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-sm">
          <div className="bg-white rounded-2xl p-7 w-full max-w-sm shadow-xl text-center">
            <div className="w-12 h-12 mx-auto bg-rose-50 rounded-full flex items-center justify-center mb-4">
              <i className="ri-delete-bin-line text-rose-500 text-xl" />
            </div>
            <h3 className="font-bold text-gray-900 mb-1">Delete Book?</h3>
            <p className="text-gray-400 text-sm mb-6">This action cannot be undone.</p>
            <div className="flex gap-3">
              <button
                onClick={() => setConfirmDelete(null)}
                className="flex-1 py-2.5 bg-gray-100 hover:bg-gray-200 text-gray-700 font-semibold text-sm rounded-xl cursor-pointer transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => { deleteBook(confirmDelete); setConfirmDelete(null); }}
                className="flex-1 py-2.5 bg-rose-500 hover:bg-rose-600 text-white font-semibold text-sm rounded-xl cursor-pointer transition-colors"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}

      {modalOpen && (
        <BookFormModal
          book={editingBook}
          onClose={() => { setModalOpen(false); setEditingBook(null); }}
        />
      )}

      {categoryModalOpen && (
        <CategoryFormModal onClose={() => setCategoryModalOpen(false)} />
      )}
    </div>
  );
}
