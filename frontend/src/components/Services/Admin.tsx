// src/services/Admin.ts

import apiClient from "../../services/api";

/* ============================================
 * TYPES
 * ============================================
 */

export interface DashboardSummary {
  documentsProcessed: number;
  activeUsers: number;
  totalThreats: number;
  quarantinedItems: number;
  complianceScore: number;
  systemHealth: string;
  storageUsedGb: number;
  uptimePercentage: number;
}

export interface ThreatScanRequest {
  text: string;
  use_ai?: boolean;
}

export interface ThreatScanResponse {
  isThreat: boolean;
  confidence: number;
  severity: "low" | "medium" | "high" | "critical";
  category: string;
  explanation: string;
  recommendations: string[];
}

export interface ThreatEvent {
  id: string;
  timestamp: string;
  severity: string;
  category: string;
  source: string;
  status: string;
  description: string;
}

export interface QuarantineItem {
  id: string;
  documentId: string;
  filename: string;
  severity: string;
  reason: string;
  quarantinedAt: string;
  status: string;
}

export interface ComplianceStatus {
  framework: string;
  status: string;
  score: number;
  lastChecked: string;
}

export interface AuditEvent {
  id: string;
  actor: string;
  action: string;
  resource: string;
  timestamp: string;
  outcome: string;
}

export interface SystemHealth {
  status: string;
  cpuUsage: number;
  memoryUsage: number;
  diskUsage: number;
  uptimeSeconds: number;
}

/* ============================================
 * DASHBOARD
 * ============================================
 */

export async function getDashboard() {
  return apiClient<DashboardSummary>("/api/v1/admin/dashboard");
}

export async function refreshDashboard() {
  return apiClient<DashboardSummary>(
    "/api/v1/admin/dashboard/refresh",
    { method: "POST" }
  );
}

/* ============================================
 * THREAT DETECTION
 * ============================================
 */

export async function threatScan(
  payload: ThreatScanRequest
) {
  return apiClient<ThreatScanResponse>(
    "/api/v1/admin/threat-scan",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }
  );
}

export async function getThreatEvents(
  page = 1,
  pageSize = 50
) {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  return apiClient<ThreatEvent[]>(`/api/v1/admin/threats?${params}`);
}

export async function acknowledgeThreat(
  threatId: string
) {
  return apiClient(`/api/v1/admin/threats/${threatId}/acknowledge`, {
    method: "POST",
  });
}

export async function resolveThreat(
  threatId: string
) {
  return apiClient(`/api/v1/admin/threats/${threatId}/resolve`, {
    method: "POST",
  });
}

/* ============================================
 * QUARANTINE
 * ============================================
 */

export async function getQuarantineItems() {
  return apiClient<QuarantineItem[]>("/api/v1/admin/quarantine");
}

export async function releaseQuarantineItem(
  itemId: string
) {
  return apiClient(`/api/v1/admin/quarantine/${itemId}/release`, {
    method: "POST",
  });
}

export async function deleteQuarantineItem(
  itemId: string
) {
  return apiClient(`/api/v1/admin/quarantine/${itemId}`, {
    method: "DELETE",
  });
}

/* ============================================
 * COMPLIANCE
 * ============================================
 */

export async function getComplianceStatus() {
  return apiClient<ComplianceStatus[]>("/api/v1/admin/compliance");
}

export async function runComplianceScan() {
  return apiClient("/api/v1/admin/compliance/scan", { method: "POST" });
}

/* ============================================
 * AUDIT
 * ============================================
 */

export async function getAuditEvents(
  page = 1,
  pageSize = 100
) {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  return apiClient<AuditEvent[]>(`/api/v1/admin/audit?${params}`);
}

export async function exportAuditLogs(
  format: "csv" | "json" = "csv"
) {
  const params = new URLSearchParams({ format });
  return apiClient<Blob>(`/api/v1/admin/audit/export?${params}`);
}

/* ============================================
 * HEALTH & OBSERVABILITY
 * ============================================
 */

export async function getSystemHealth() {
  return apiClient<SystemHealth>("/api/v1/admin/health");
}

export async function getMetrics() {
  return apiClient("/api/v1/admin/metrics");
}

export async function getPrometheusMetrics() {
  return apiClient("/api/v1/admin/prometheus");
}

/* ============================================
 * SECURITY POLICIES
 * ============================================
 */

export async function getPolicies() {
  return apiClient("/api/v1/admin/policies");
}

export async function updatePolicy(
  policyId: string,
  payload: Record<string, unknown>
) {
  return apiClient(`/api/v1/admin/policies/${policyId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

/* ============================================
 * USERS
 * ============================================
 */

export async function getAdminUsers() {
  return apiClient("/api/v1/admin/users");
}

export async function getUserPermissions(
  userId: string
) {
  return apiClient(`/api/v1/admin/users/${userId}/permissions`);
}