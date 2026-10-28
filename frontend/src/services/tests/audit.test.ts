/**
 * Unit tests for AuditService client methods.
 * Path: frontend/src/services/__tests__/audit.test.ts
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import AuditService, { ApiError, clearAuditCache } from "../audit";
import { apiClient } from "../api";

// Mock the base apiClient module
vi.mock("../api", async () => {
  const actual = await vi.importActual<typeof import("../api")>("../api");
  return {
    ...actual,
    apiClient: {
      get: vi.fn(),
      post: vi.fn(),
      getBaseUrl: vi.fn(() => "http://localhost:8000"),
      getAccessToken: vi.fn(() => "mock-jwt-token"),
    },
  };
});

describe("AuditService", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearAuditCache();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe("list", () => {
    it("should fetch audit events with correctly formatted query parameters", async () => {
      const mockResponse = {
        items: [
          { id: "evt-1", ts: "2026-10-27T10:00:00Z", action: "login", severity: "info" },
        ],
        total: 1,
      };

      vi.mocked(apiClient.get).mockResolvedValueOnce(mockResponse);

      const result = await AuditService.list({
        severity: ["info", "low"],
        action: ["login", "logout"],
        page: 1,
        page_size: 10,
      });

      expect(apiClient.get).toHaveBeenCalledWith(
        "/api/v1/audit/events",
        expect.objectContaining({
          params: expect.objectContaining({
            severity: "info,low",
            action: "login,logout",
            page: 1,
            page_size: 10,
          }),
        })
      );
      expect(result).toEqual(mockResponse);
    });
  });

  describe("getSummary", () => {
    it("should cache summary results and respect skipCache option", async () => {
      const mockSummary = {
        total_events: 150,
        failed_auth_count: 3,
        by_action: [],
        by_severity: [],
        by_actor: [],
        period: { from: "2026-10-01", to: "2026-10-27" },
      };

      vi.mocked(apiClient.get).mockResolvedValueOnce(mockSummary);

      // First call (should hit API)
      const firstResult = await AuditService.getSummary();
      expect(apiClient.get).toHaveBeenCalledTimes(1);
      expect(firstResult).toEqual(mockSummary);

      // Second call (should hit cache, API call count remains 1)
      const cachedResult = await AuditService.getSummary();
      expect(apiClient.get).toHaveBeenCalledTimes(1);
      expect(cachedResult).toEqual(mockSummary);

      // Third call with skipCache (should hit API again)
      vi.mocked(apiClient.get).mockResolvedValueOnce(mockSummary);
      await AuditService.getSummary(undefined, { skipCache: true });
      expect(apiClient.get).toHaveBeenCalledTimes(2);
    });
  });

  describe("export", () => {
    it("should post export requests with the correct format and parameters", async () => {
      const mockExportResult = {
        job_id: "job-123",
        status: "processing" as const,
      };

      vi.mocked(apiClient.post).mockResolvedValueOnce(mockExportResult);

      const result = await AuditService.export({ format: "csv", window: "24h" });

      expect(apiClient.post).toHaveBeenCalledWith(
        "/api/v1/audit/export",
        { format: "csv", window: "24h" },
        expect.any(Object)
      );
      expect(result).toEqual(mockExportResult);
    });
  });
});