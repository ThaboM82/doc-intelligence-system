import ThreatSummary from "../components/security/ThreatSummary";

const DashboardPage = () => {
  return (
    <div className="space-y-6">
      <ThreatSummary />

      <div className="card">
        <h2>
          Welcome to Document
          Intelligence
        </h2>

        <p className="mt-2 text-muted">
          Monitor uploads,
          document analysis,
          OCR processing,
          AI chats and
          security events.
        </p>
      </div>
    </div>
  );
};

export default DashboardPage;