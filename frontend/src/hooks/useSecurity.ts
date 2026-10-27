import React, { useState, useEffect, useCallback } from "react";
import { 
  ShieldAlert, 
  Lock, 
  FileLock2, 
  Activity, 
  RefreshCw, 
  Download, 
  AlertTriangle,
  CheckCircle2
} from "lucide-react";
import { PageHeader } from "../components/Common/PageHeader";
import LoadingSpinner from "../components/Common/LoadingSpinner";
import ErrorState from "../components/Common/ErrorState";
import SecurityDashboard from "../components/Security/SecurityDashboard";
import QuarantineTable from "../components/Security/QuarantineTable";
import ThreatEventsTable from "../components/Security/ThreatEventsTable";
import ComplianceStatus from "../components/enterprise/ComplianceStatus";
import { useSecurity } from "../hooks/useSecurity";

type SecurityTab = "overview" | "threats" | "quarantine" | "compliance";

const SecurityPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<SecurityTab>("overview");
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [lastSynced, setLastSynced] = useState<Date>(new Date());
  
  const { 
    metrics, 
    threats, 
    quarantinedItems, 
    isLoading, 
    error, 
    fetchSecurityData, 
    exportAuditLogs 
  } = useSecurity();

  // Handle manual data refresh with loading state
  const handleRefresh = useCallback(async () => {
    setIsRefreshing(true);
    try {
      await fetchSecurityData();
      setLastSynced(new Date());
    } catch (err) {
      console.error("Failed to refresh security data:", err);
    } finally {
      setIsRefreshing(false);
    }
  }, [fetchSecurityData]);

  // Auto-refresh interval for enterprise real-time monitoring (every 60 seconds)
  useEffect(() => {
    const interval = setInterval(() => {
      fetchSecurityData();
      setLastSynced(new Date());
    }, 60000);
    return () => clearInterval(interval);
  }, [fetchSecurityData]);

  if (isLoading && !metrics) {
    return (
      <div className="flex h-96 w-full items-center justify-center">
        <LoadingSpinner size="lg" message="Loading enterprise security telemetry..." />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6">
        <ErrorState 
          title="Security Telemetry Error" 
          message={error} 
          onRetry={handleRefresh} 
        />
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6">
      {/* Page Header with Actions */}
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <PageHeader 
          title="Security & Governance Operations" 
          subtitle={`Last synced: ${lastSynced.toLocaleTimeString()} | Active Threat Protection: Online`}
        />
        <div className="flex items-center gap-3">
          <button
            onClick={handleRefresh}
            disabled={isRefreshing}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-sm font-medium text-slate-200 transition hover:bg-slate-700 disabled:opacity-50"
            title="Refresh Security Telemetry"
          >
            <RefreshCw className={`h-4 w-4 ${isRefreshing ? "animate-spin" : ""}`} />
            Refresh
          </button>
          <button
            onClick={() => exportAuditLogs()}
            className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500"
          >
            <Download className="h-4 w-4" />
            Export Audit Log
          </button>
        </div>
      </div>

      {/* Security Status Banner */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div className="flex items-center gap-4 rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <div className="rounded-lg bg-emerald-500/10 p-3 text-emerald-400">
            <CheckCircle2 className="h-6 w-6" />
          </div>
          <div>
            <p className="text-xs font-medium text-slate-400">DLP Firewall</p>
            <p className="text-lg font-bold text-slate-100">Active & Enforcing</p>
          </div>
        </div>
        <div className="flex items-center gap-4 rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <div className="rounded-lg bg-amber-500/10 p-3 text-amber-400">
            <AlertTriangle className="h-6 w-6" />
          </div>
          <div>
            <p className="text-xs font-medium text-slate-400">Quarantine Queue</p>
            <p className="text-lg font-bold text-slate-100">{quarantinedItems?.length || 0} Items Held</p>
          </div>
        </div>
        <div className="flex items-center gap-4 rounded-xl border border-slate-800 bg-slate-900/50 p-4">
          <div className="rounded-lg bg-indigo-500/10 p-3 text-indigo-400">
            <Activity className="h-6 w-6" />
          </div>
          <div>
            <p className="text-xs font-medium text-slate-400">Threat Events (24h)</p>
            <p className="text-lg font-bold text-slate-100">{threats?.length || 0} Detected</p>
          </div>
        </div>
      </div>

      {/* Enterprise Navigation Tabs */}
      <div className="border-b border-slate-800">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => setActiveTab("overview")}
            className={`flex items-center gap-2 border-b-2 pb-4 text-sm font-medium transition ${
              activeTab === "overview"
                ? "border-indigo-500 text-indigo-400"
                : "border-transparent text-slate-400 hover:border-slate-600 hover:text-slate-300"
            }`}
          >
            <ShieldAlert className="h-4 w-4" />
            Overview Dashboard
          </button>
          <button
            onClick={() => setActiveTab("threats")}
            className={`flex items-center gap-2 border-b-2 pb-4 text-sm font-medium transition ${
              activeTab === "threats"
                ? "border-indigo-500 text-indigo-400"
                : "border-transparent text-slate-400 hover:border-slate-600 hover:text-slate-300"
            }`}
          >
            <Activity className="h-4 w-4" />
            Threat Events
          </button>
          <button
            onClick={() => setActiveTab("quarantine")}
            className={`flex items-center gap-2 border-b-2 pb-4 text-sm font-medium transition ${
              activeTab === "quarantine"
                ? "border-indigo-500 text-indigo-400"
                : "border-transparent text-slate-400 hover:border-slate-600 hover:text-slate-300"
            }`}
          >
            <FileLock2 className="h-4 w-4" />
            Quarantine Manager
          </button>
          <button
            onClick={() => setActiveTab("compliance")}
            className={`flex items-center gap-2 border-b-2 pb-4 text-sm font-medium transition ${
              activeTab === "compliance"
                ? "border-indigo-500 text-indigo-400"
                : "border-transparent text-slate-400 hover:border-slate-600 hover:text-slate-300"
            }`}
          >
            <Lock className="h-4 w-4" />
            Compliance & Audit
          </button>
        </nav>
      </div>

      {/* Tab Content Render Area */}
      <div className="mt-6">
        {activeTab === "overview" && <SecurityDashboard data={metrics} />}
        {activeTab === "threats" && <ThreatEventsTable events={threats} onRefresh={handleRefresh} />}
        {activeTab === "quarantine" && <QuarantineTable items={quarantinedItems} onUpdate={handleRefresh} />}
        {activeTab === "compliance" && <ComplianceStatus />}
      </div>
    </div>
  );
};

export default SecurityPage;