import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { NewInvestigation } from "./pages/NewInvestigation";
import { CaseDetail } from "./pages/CaseDetail";
import { Cases } from "./pages/Cases";
import { Compare } from "./pages/Compare";
import { Evidence } from "./pages/Evidence";
import { HowItWorks } from "./pages/HowItWorks";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<NewInvestigation />} />
        <Route path="cases" element={<Cases />} />
        <Route path="cases/:id" element={<CaseDetail />} />
        <Route path="compare" element={<Compare />} />
        <Route path="evidence" element={<Evidence />} />
        <Route path="how-it-works" element={<HowItWorks />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
