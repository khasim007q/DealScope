import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { NewInvestigation } from "./pages/NewInvestigation";
import { CaseDetail } from "./pages/CaseDetail";
import { Cases } from "./pages/Cases";
import { HowItWorks } from "./pages/HowItWorks";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<NewInvestigation />} />
        <Route path="cases" element={<Cases />} />
        <Route path="cases/:id" element={<CaseDetail />} />
        <Route path="how-it-works" element={<HowItWorks />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
