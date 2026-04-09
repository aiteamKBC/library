import { useState } from "react";

const steps = [
  {
    number: "01",
    title: "Search & Browse",
    description: "Use the search bar to find books by title or author, or open the categories page to browse the collection.",
    icon: "ri-search-2-line",
    color: "#442F73",
  },
  {
    number: "02",
    title: "Open a Category",
    description: "Each category groups related books together so you can quickly see what is available in that area.",
    icon: "ri-grid-line",
    color: "#2D6A4F",
  },
  {
    number: "03",
    title: "Review Book Details",
    description: "Open a book card to view its title, author, and category without any extra placeholder data.",
    icon: "ri-book-open-line",
    color: "#B27715",
  },
  {
    number: "04",
    title: "Ask for Help",
    description: "If the book you need is not listed, send a message to the library team from the support page.",
    icon: "ri-customer-service-2-line",
    color: "#9D2B2B",
  },
];

export default function GuidanceSection() {
  const [activeStep, setActiveStep] = useState(0);

  return (
    <section className="py-20 bg-[#F9F4EC]">
      <div className="max-w-7xl mx-auto px-4 md:px-6">
        <div className="text-center mb-14">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-[#442F73]/8 border border-[#442F73]/15 rounded-full mb-3">
            <i className="ri-map-pin-user-line text-[#442F73] text-xs" />
            <span className="text-[#442F73] text-xs font-semibold tracking-wide uppercase">Getting Started</span>
          </div>
          <h2 className="text-3xl md:text-4xl font-bold text-[#241453] mb-3" style={{ fontFamily: "'Playfair Display', serif" }}>
            How to Use the KBC Digital Library
          </h2>
          <p className="text-gray-500 text-sm max-w-md mx-auto">
            Follow these simple steps to work with the current book list and request help when needed.
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
          <div className="space-y-4">
            {steps.map((step, idx) => (
              <button
                key={step.number}
                onClick={() => setActiveStep(idx)}
                className={`w-full flex items-start gap-5 p-5 rounded-2xl border text-left transition-all duration-300 cursor-pointer ${
                  activeStep === idx
                    ? "bg-white border-[#442F73]/20 shadow-sm"
                    : "bg-transparent border-[#E9D9BD] hover:border-[#DDC398] hover:bg-white/50"
                }`}
              >
                <div
                  className={`w-12 h-12 flex-none flex items-center justify-center rounded-xl font-bold text-sm transition-all duration-300 ${
                    activeStep === idx ? "text-white" : "text-gray-400 bg-[#E9D9BD]"
                  }`}
                  style={activeStep === idx ? { backgroundColor: step.color } : {}}
                >
                  {step.number}
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className={`font-semibold text-sm mb-1 transition-colors duration-200 ${activeStep === idx ? "text-[#241453]" : "text-gray-600"}`}>
                    {step.title}
                  </h3>
                  <p className="text-gray-500 text-xs leading-relaxed">{step.description}</p>
                </div>
                {activeStep === idx && (
                  <div className="w-5 h-5 flex-none flex items-center justify-center rounded-full mt-0.5" style={{ backgroundColor: `${steps[idx].color}15` }}>
                    <i className="ri-check-line text-xs" style={{ color: steps[idx].color }} />
                  </div>
                )}
              </button>
            ))}
          </div>

          <div
            className="rounded-3xl overflow-hidden relative aspect-[4/3] flex items-center justify-center transition-all duration-500"
            style={{ background: `linear-gradient(135deg, ${steps[activeStep].color}15, ${steps[activeStep].color}30)` }}
          >
            <div
              className="absolute inset-0 opacity-5"
              style={{ backgroundImage: `radial-gradient(${steps[activeStep].color} 1px, transparent 1px)`, backgroundSize: "20px 20px" }}
            />
            <div className="text-center px-8 relative z-10">
              <div
                className="w-24 h-24 flex items-center justify-center rounded-3xl mx-auto mb-6 transition-all duration-300"
                style={{ backgroundColor: `${steps[activeStep].color}20` }}
              >
                <i
                  className={`${steps[activeStep].icon} text-5xl transition-colors duration-300`}
                  style={{ color: steps[activeStep].color }}
                />
              </div>
              <h3
                className="text-2xl font-bold mb-3 transition-colors duration-300"
                style={{ fontFamily: "'Playfair Display', serif", color: steps[activeStep].color }}
              >
                {steps[activeStep].title}
              </h3>
              <p className="text-gray-600 text-sm leading-relaxed max-w-xs mx-auto">
                {steps[activeStep].description}
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
