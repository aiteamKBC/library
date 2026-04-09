import { useState } from "react";

const faqs = [
  {
    id: 1,
    question: "How do I search for a book?",
    answer: "Use the search bar on the Resources page to search by book title or author name.",
    category: "Search",
  },
  {
    id: 2,
    question: "How are books grouped in the library?",
    answer: "Books are organised into categories so you can browse related titles together on the Categories and Resources pages.",
    category: "Categories",
  },
  {
    id: 3,
    question: "What information is shown for each book?",
    answer: "The current library pages show the real fields available in the dataset: book title, author, and category.",
    category: "Search",
  },
  {
    id: 4,
    question: "What should I do if I can't find the book I need?",
    answer: "Use the contact form on this page to message the library team and explain what book you are looking for.",
    category: "Support",
  },
  {
    id: 5,
    question: "Can I browse the library on mobile?",
    answer: "Yes. The library interface is responsive, so you can browse books and categories from desktop or mobile screens.",
    category: "Access",
  },
];

const categories = ["All", "Search", "Categories", "Support", "Access"];

export default function FAQSection() {
  const [openId, setOpenId] = useState<number | null>(null);
  const [activeCategory, setActiveCategory] = useState("All");
  const [faqSearch, setFaqSearch] = useState("");

  const filtered = faqs.filter((faq) => {
    const matchCat = activeCategory === "All" || faq.category === activeCategory;
    const matchSearch =
      faqSearch.trim() === "" ||
      faq.question.toLowerCase().includes(faqSearch.toLowerCase()) ||
      faq.answer.toLowerCase().includes(faqSearch.toLowerCase());
    return matchCat && matchSearch;
  });

  return (
    <section className="py-20 bg-white">
      <div className="max-w-4xl mx-auto px-4 md:px-6">
        <div className="text-center mb-12">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-[#442F73]/8 border border-[#442F73]/15 rounded-full mb-3">
            <i className="ri-question-answer-line text-[#442F73] text-xs" />
            <span className="text-[#442F73] text-xs font-semibold tracking-wide uppercase">Frequently Asked Questions</span>
          </div>
          <h2 className="text-3xl md:text-4xl font-bold text-[#241453] mb-3" style={{ fontFamily: "'Playfair Display', serif" }}>
            Common Student Questions
          </h2>
          <p className="text-gray-500 text-sm max-w-md mx-auto">
            Short answers based on the features currently available in the library.
          </p>
        </div>

        <div className="relative mb-6">
          <i className="ri-search-line absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 text-sm" />
          <input
            type="text"
            value={faqSearch}
            onChange={(e) => setFaqSearch(e.target.value)}
            placeholder="Search frequently asked questions..."
            className="w-full pl-10 pr-4 py-3 text-sm bg-[#F9F4EC] border border-[#E9D9BD] rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800 placeholder-gray-400"
          />
        </div>

        <div className="flex flex-wrap gap-2 mb-8">
          {categories.map((category) => (
            <button
              key={category}
              onClick={() => setActiveCategory(category)}
              className={`px-3.5 py-1.5 rounded-full text-xs font-semibold transition-all duration-200 cursor-pointer whitespace-nowrap ${
                activeCategory === category
                  ? "bg-[#442F73] text-white"
                  : "bg-[#F9F4EC] text-gray-600 hover:bg-[#E9D9BD] hover:text-[#442F73] border border-[#E9D9BD]"
              }`}
            >
              {category}
            </button>
          ))}
        </div>

        <div className="space-y-3">
          {filtered.length === 0 ? (
            <div className="text-center py-12 text-gray-400">
              <i className="ri-search-line text-3xl mb-2 block" />
              <p className="text-sm">No FAQs match your search. Try different keywords.</p>
            </div>
          ) : (
            filtered.map((faq) => (
              <div
                key={faq.id}
                className={`bg-white rounded-2xl border transition-all duration-300 overflow-hidden ${
                  openId === faq.id ? "border-[#442F73]/25 shadow-sm" : "border-[#E9D9BD] hover:border-[#DDC398]"
                }`}
              >
                <button
                  onClick={() => setOpenId(openId === faq.id ? null : faq.id)}
                  className="w-full flex items-start justify-between gap-4 px-6 py-5 text-left cursor-pointer"
                >
                  <div className="flex items-start gap-3 flex-1 min-w-0">
                    <div
                      className={`w-7 h-7 flex-none flex items-center justify-center rounded-lg mt-0.5 transition-colors duration-200 ${
                        openId === faq.id ? "bg-[#442F73] text-white" : "bg-[#F9F4EC] text-[#442F73]"
                      }`}
                    >
                      <i className="ri-question-line text-xs" />
                    </div>
                    <span className="font-semibold text-[#241453] text-sm leading-snug">{faq.question}</span>
                  </div>
                  <div
                    className={`w-7 h-7 flex-none flex items-center justify-center rounded-lg transition-all duration-300 ${
                      openId === faq.id ? "bg-[#442F73]/8 text-[#442F73] rotate-180" : "text-gray-400"
                    }`}
                  >
                    <i className="ri-arrow-down-s-line" />
                  </div>
                </button>
                {openId === faq.id && (
                  <div className="px-6 pb-6">
                    <div className="pl-10">
                      <p className="text-gray-600 text-sm leading-relaxed">{faq.answer}</p>
                      <span className="inline-block mt-3 px-2.5 py-1 rounded-full text-xs font-medium bg-[#442F73]/8 text-[#442F73]">
                        {faq.category}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </section>
  );
}
