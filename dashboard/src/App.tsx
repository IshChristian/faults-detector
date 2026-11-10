import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { LoginPage } from "./auth/LoginPage";
import { RequireAuth } from "./auth/RequireAuth";
import { homePath } from "./auth/types";
import { AppShell } from "./layout/AppShell";
import { Cameras } from "./pages/Cameras";
import { FaultCenter } from "./pages/FaultCenter";
import { LiveOperations } from "./pages/LiveOperations";
import { NotFound } from "./pages/NotFound";
import { Sessions } from "./pages/Sessions";
import { CalibrationPage } from "./sessions/CalibrationPage";
import { NewSessionForm } from "./sessions/NewSessionForm";
import { SessionDetail } from "./sessions/SessionDetail";
import { Settings } from "./pages/Settings";

function Home() {
  const { user } = useAuth();
  return <Navigate to={user ? homePath(user) : "/login"} replace />;
}

export function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <RequireAuth>
                <AppShell />
              </RequireAuth>
            }
          >
            <Route index element={<Home />} />
            <Route path="live" element={<LiveOperations />} />
            <Route path="faults" element={<FaultCenter />} />
            <Route path="sessions" element={<Sessions />} />
            <Route path="sessions/new" element={<NewSessionForm />} />
            <Route path="sessions/:id/calibrate" element={<CalibrationPage />} />
            <Route path="sessions/:id" element={<SessionDetail />} />
            <Route path="cameras" element={<Cameras />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
