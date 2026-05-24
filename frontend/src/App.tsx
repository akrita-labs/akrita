import { Routes, Route } from "react-router-dom";
import HomePage from "./pages/HomePage";
import DashboardPage from "./pages/DashboardPage";
import TracePage from "./pages/TracePage";
import BuilderPage from "./pages/BuilderPage";
import AboutPage from "./pages/AboutPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<HomePage />} />
      <Route path="/dashboard" element={<DashboardPage />} />
      <Route path="/trace" element={<TracePage />} />
      <Route path="/builder" element={<BuilderPage />} />
      <Route path="/about" element={<AboutPage />} />
      {/* Fallback route */}
      <Route path="*" element={<HomePage />} />
    </Routes>
  );
}
