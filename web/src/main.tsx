import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { MaxUI } from "@maxhub/max-ui";
import "@maxhub/max-ui/dist/styles.css";
import "./styles.css";
import App from "./App";
import Home from "./pages/Home";
import RoutePage from "./pages/RoutePage";
import StepCard from "./pages/StepCard";
import Builder from "./pages/Builder";
import Orgs from "./pages/Orgs";
import OrgDetail from "./pages/OrgDetail";
import Reminders from "./pages/Reminders";
import HealthHub from "./pages/HealthHub";
import HealthDiary from "./pages/HealthDiary";
import Report from "./pages/Report";
import Meds from "./pages/Meds";
import Family from "./pages/Family";
import Profile from "./pages/Profile";
import About from "./pages/About";
import Onboarding from "./pages/Onboarding";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MaxUI resetBody={false} colorScheme="light" className="max-ui-root">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<App />}>
            <Route index element={<Home />} />
            <Route path="route" element={<RoutePage />} />
            <Route path="step/:stepId" element={<StepCard />} />
            <Route path="builder" element={<Builder />} />
            <Route path="orgs" element={<Orgs />} />
            <Route path="orgs/:orgId" element={<OrgDetail />} />
            <Route path="reminders" element={<Reminders />} />
            <Route path="health" element={<HealthHub />} />
            <Route path="health/report" element={<Report />} />
            <Route path="health/:type" element={<HealthDiary />} />
            <Route path="meds" element={<Meds />} />
            <Route path="family" element={<Family />} />
            <Route path="profile" element={<Profile />} />
            <Route path="about" element={<About />} />
            <Route path="onboarding" element={<Onboarding />} />
            <Route path="catalog" element={<Navigate to="/builder" replace />} />
            <Route path="*" element={<Home />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </MaxUI>
  </StrictMode>,
);
