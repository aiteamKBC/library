import { useEffect, useState, FormEvent } from "react";
import { useAdminData } from "../../../hooks/useAdminData";
import { useLibrarySession } from "../../../hooks/useLibrarySession";

type FieldName = "name" | "email" | "subject" | "message" | "course";

export default function LibrarianContact() {
  const { addSupportMessage } = useAdminData();
  const { user } = useLibrarySession();
  const [form, setForm] = useState({
    name: "",
    email: "",
    course: "",
    subject: "",
    message: "",
  });
  const [submitted, setSubmitted] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [charCount, setCharCount] = useState(0);

  useEffect(() => {
    if (!user) return;
    setForm((prev) => ({
      ...prev,
      name: prev.name || user.fullName || "",
      email: prev.email || user.email || "",
    }));
  }, [user]);

  const handleChange = (field: FieldName, value: string) => {
    if (field === "message") {
      if (value.length > 500) return;
      setCharCount(value.length);
    }
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (form.message.length > 500) return;
    setSubmitting(true);
    try {
      await addSupportMessage({
        fullName: form.name,
        email: form.email,
        course: form.course,
        subject: form.subject,
        message: form.message,
      });
      setSubmitted(true);
    } catch {
      setSubmitted(false);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className="py-20 bg-[#F9F4EC]">
      <div className="max-w-3xl mx-auto px-4 md:px-6">
        <div className="text-center mb-14">
          <div className="inline-flex items-center gap-2 px-3 py-1.5 bg-[#442F73]/8 border border-[#442F73]/15 rounded-full mb-3">
            <i className="ri-customer-service-2-line text-[#442F73] text-xs" />
            <span className="text-[#442F73] text-xs font-semibold tracking-wide uppercase">Get in Touch</span>
          </div>
          <h2 className="text-3xl md:text-4xl font-bold text-[#241453] mb-3" style={{ fontFamily: "'Playfair Display', serif" }}>
            Contact a Librarian
          </h2>
          <p className="text-gray-500 text-sm max-w-md mx-auto">
            Send a message if you need help finding a book or want to ask about the current library list.
          </p>
        </div>

        <div>
          <div className="bg-white rounded-2xl border border-[#E9D9BD] p-6 md:p-8">
            <h3 className="font-semibold text-[#241453] text-base mb-1">Send Us a Message</h3>
            <p className="text-gray-400 text-xs mb-6">Use the form below to contact the library team.</p>

            {submitted ? (
              <div className="flex flex-col items-center justify-center text-center py-12">
                <div className="w-16 h-16 flex items-center justify-center rounded-full bg-emerald-50 mb-4">
                  <i className="ri-check-double-line text-3xl text-emerald-500" />
                </div>
                <h4 className="font-bold text-[#241453] text-lg mb-2">Message Sent!</h4>
                <p className="text-gray-500 text-sm max-w-xs">
                  Thanks for reaching out. Your message has been submitted successfully.
                </p>
              </div>
            ) : (
              <form
                data-readdy-form
                id="contact-librarian-form"
                onSubmit={handleSubmit}
                className="space-y-4"
              >
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1.5">Full Name <span className="text-red-400">*</span></label>
                    <input
                      type="text"
                      name="name"
                      required
                      value={form.name}
                      onChange={(e) => handleChange("name", e.target.value)}
                      placeholder="Enter your full name"
                      className="w-full px-4 py-2.5 text-sm bg-[#F9F4EC] border border-[#E9D9BD] rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800 placeholder-gray-400"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1.5">Email Address <span className="text-red-400">*</span></label>
                    <input
                      type="email"
                      name="email"
                      required
                      value={form.email}
                      onChange={(e) => handleChange("email", e.target.value)}
                      placeholder="Enter your email address"
                      className="w-full px-4 py-2.5 text-sm bg-[#F9F4EC] border border-[#E9D9BD] rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800 placeholder-gray-400"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1.5">Your Course / Programme</label>
                  <input
                    type="text"
                    name="course"
                    value={form.course}
                    onChange={(e) => handleChange("course", e.target.value)}
                    placeholder="Enter your course or programme"
                    className="w-full px-4 py-2.5 text-sm bg-[#F9F4EC] border border-[#E9D9BD] rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800 placeholder-gray-400"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1.5">Message Subject <span className="text-red-400">*</span></label>
                  <input
                    type="text"
                    name="subject"
                    required
                    value={form.subject}
                    onChange={(e) => handleChange("subject", e.target.value)}
                    placeholder="Enter your message subject"
                    className="w-full px-4 py-2.5 text-sm bg-[#F9F4EC] border border-[#E9D9BD] rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800 placeholder-gray-400"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1.5">
                    Message <span className="text-red-400">*</span>
                    <span className={`ml-2 font-normal ${charCount > 450 ? "text-red-400" : "text-gray-400"}`}>
                      {charCount}/500
                    </span>
                  </label>
                  <textarea
                    name="message"
                    required
                    rows={5}
                    value={form.message}
                    onChange={(e) => handleChange("message", e.target.value)}
                    placeholder="Enter your message"
                    className="w-full px-4 py-3 text-sm bg-[#F9F4EC] border border-[#E9D9BD] rounded-xl outline-none focus:border-[#442F73] focus:ring-2 focus:ring-[#442F73]/10 text-gray-800 placeholder-gray-400 resize-none"
                  />
                </div>

                <button
                  type="submit"
                  disabled={submitting || form.message.length > 500}
                  className="w-full flex items-center justify-center gap-2 py-3.5 bg-[#241453] hover:bg-[#442F73] disabled:opacity-60 text-white font-bold text-sm rounded-xl transition-colors duration-200 cursor-pointer whitespace-nowrap"
                >
                  {submitting ? (
                    <>
                      <i className="ri-loader-4-line animate-spin" />
                      Sending...
                    </>
                  ) : (
                    <>
                      <i className="ri-send-plane-2-line" />
                      Send Message
                    </>
                  )}
                </button>
              </form>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
