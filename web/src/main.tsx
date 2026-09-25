import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { MaxUI } from "@maxhub/max-ui";
import "@maxhub/max-ui/dist/styles.css";
import "./styles.css";
import App from "./App";
import Dashboard from "./pages/Dashboard";
import Catalog from "./pages/Catalog";
import RoutePage from "./pages/RoutePage";
import StepCard from "./pages/StepCard";
import NextStep from "./pages/NextStep";
import Checklist from "./pages/Checklist";
import Orgs from "./pages/Orgs";
import OrgDetail from "./pages/OrgDetail";
import Prep from "./pages/Prep";
import Reminders from "./pages/Reminders";
import Health from "./pages/Health";
import Family from "./pages/Family";
import Profile from "./pages/Profile";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MaxUI resetBody={false} colorScheme="light" className="max-ui-root">
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<Dashboard />} />
          <Route path="catalog" element={<Catalog />} />
          <Route path="route" element={<RoutePage />} />
          <Route path="step/:stepId" element={<StepCard />} />
          <Route path="next-step" element={<NextStep />} />
          <Route path="checklist" element={<Checklist />} />
          <Route path="orgs" element={<Orgs />} />
          <Route path="orgs/:orgId" element={<OrgDetail />} />
          <Route path="prep" element={<Prep />} />
          <Route path="reminders" element={<Reminders />} />
          <Route path="health" element={<Health />} />
          <Route path="family" element={<Family />} />
          <Route path="profile" element={<Profile />} />
          <Route path="*" element={<Dashboard />} />
        </Route>
      </Routes>
    </BrowserRouter>
    </MaxUI>
  </StrictMode>,
);
