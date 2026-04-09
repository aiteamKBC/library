import Navbar from "../../components/feature/Navbar";
import Footer from "../../components/feature/Footer";
import HeroSection from "./components/HeroSection";
import CategoryHighlights from "./components/CategoryHighlights";
import PopularResources from "./components/PopularResources";
import BenefitsSection from "./components/BenefitsSection";

export default function HomePage() {
  return (
    <div className="min-h-screen bg-white">
      <Navbar />
      <main>
        <HeroSection />
        <CategoryHighlights />
        <PopularResources />
        <BenefitsSection />
      </main>
      <Footer />
    </div>
  );
}
