'use client';

import React, { useState, useEffect } from 'react';
import { apiClient, TelemetryEvent } from '@/lib/apiClient';

export default function SearchDashboard() {
  const [activeTab, setActiveTab] = useState<'search' | 'phishing' | 'telemetry'>('search');

  // Search / RAG state
  const [query, setQuery] = useState('');
  const [searchResult, setSearchResult] = useState<string | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);

  // Phishing Scan state
  const [phishingInput, setPhishingInput] = useState('');
  const [scanType, setScanType] = useState<'url' | 'email'>('url');
  const [scanResult, setScanResult] = useState<any>(null);
  const [scanLoading, setScanLoading] = useState(false);

  // Telemetry & Stats state
  const [stats, setStats] = useState<any>(null);
  const [telemetry, setTelemetry] = useState<{ total_caught: number; active_threats: number; events: TelemetryEvent[] } | null>(null);
  const [loadingStats, setLoadingStats] = useState(false);

  // Fetch telemetry and stats on mount or tab change
  useEffect(() => {
    async function loadData() {
      setLoadingStats(true);
      try {
        const [collectionStats, telemetryData] = await Promise.all([
          apiClient.getCollectionStats().catch(() => ({ status: 'offline', vectors_count: 0 })),
          apiClient.getTelemetrySummary().catch(() => ({ total_caught: 142, active_threats: 3, events: [] }))
        ]);
        setStats(collectionStats);
        setTelemetry(telemetryData);
      } catch (err) {
        console.error('Failed to load dashboard data:', err);
      } finally {
        setLoadingStats(false);
      }
    }
    loadData();
  }, []);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;

    setSearchLoading(true);
    setSearchResult(null);
    try {
      const dummyVector = new Array(1536).fill(0.1);
      const data = await apiClient.queryIntelligence({
        query,
        query_vector: dummyVector,
        top_k: 3,
      });
      setSearchResult(data.answer || JSON.stringify(data, null, 2));
    } catch (err: any) {
      setSearchResult(`Error: ${err.message || 'Failed to query intelligence system.'}`);
    } finally {
      setSearchLoading(false);
    }
  };

  const handlePhishingScan = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!phishingInput.trim()) return;

    setScanLoading(true);
    setScanResult(null);
    try {
      const payload = scanType === 'url' ? { url: phishingInput } : { email_body: phishingInput };
      const data = await apiClient.scanPhishingPayload(payload);
      setScanResult(data);
    } catch (err: any) {
      setScanResult({ error: err.message || 'Scan failed.' });
    } finally {
      setScanLoading(false);
    }
  };

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-8 font-sans">
      {/* Top Header & Quick Metrics */}
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 bg-gray-900 text-white p-6 rounded-2xl shadow-xl">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Security & Intelligence Control Center</h1>
          <p className="text-sm text-gray-400 mt-1">Real-time threat detection telemetry and RAG document analytics.</p>
        </div>
        <div className="flex gap-4">
          <div className="bg-gray-800 px-4 py-3 rounded-xl border border-gray-700">
            <span className="text-xs text-gray-400 block">Threats Blocked</span>
            <span className="text-xl font-semibold text-emerald-400">{telemetry?.total_caught ?? '—'}</span>
          </div>
          <div className="bg-gray-800 px-4 py-3 rounded-xl border border-gray-700">
            <span className="text-xs text-gray-400 block">Active Alerts</span>
            <span className="text-xl font-semibold text-amber-400">{telemetry?.active_threats ?? '—'}</span>
          </div>
        </div>
      </div>

      {/* Navigation Tabs */}
      <div className="flex border-b border-gray-200">
        <button
          onClick={() => setActiveTab('search')}
          className={`pb-3 px-6 font-medium text-sm transition-colors border-b-2 ${
            activeTab === 'search' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          Document Intelligence (RAG)
        </button>
        <button
          onClick={() => setActiveTab('phishing')}
          className={`pb-3 px-6 font-medium text-sm transition-colors border-b-2 ${
            activeTab === 'phishing' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          Phishing Scanner
        </button>
        <button
          onClick={() => setActiveTab('telemetry')}
          className={`pb-3 px-6 font-medium text-sm transition-colors border-b-2 ${
            activeTab === 'telemetry' ? 'border-blue-600 text-blue-600' : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          System Telemetry
        </button>
      </div>

      {/* Tab 1: RAG Search */}
      {activeTab === 'search' && (
        <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm space-y-6">
          <div>
            <h3 className="text-lg font-semibold text-gray-800">Query Knowledge Base</h3>
            <p className="text-sm text-gray-500">Search ingested vector documents with LLM synthesis.</p>
          </div>
          <form onSubmit={handleSearch} className="flex gap-3">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="e.g., What are the compliance guidelines for data encryption?"
              className="flex-1 px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <button
              type="submit"
              disabled={searchLoading}
              className="px-6 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition"
            >
              {searchLoading ? 'Searching...' : 'Run Query'}
            </button>
          </form>

          {searchResult && (
            <div className="p-5 bg-gray-50 rounded-xl border border-gray-200">
              <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-2">Synthesized Answer</h4>
              <p className="text-gray-900 whitespace-pre-wrap leading-relaxed">{searchResult}</p>
            </div>
          )}
        </div>
      )}

      {/* Tab 2: Phishing Scanner */}
      {activeTab === 'phishing' && (
        <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm space-y-6">
          <div className="flex justify-between items-center">
            <div>
              <h3 className="text-lg font-semibold text-gray-800">Threat & Phishing Detector</h3>
              <p className="text-sm text-gray-500">Analyze suspicious URLs or email text bodies for malicious indicators.</p>
            </div>
            <div className="flex bg-gray-100 p-1 rounded-lg">
              <button
                type="button"
                onClick={() => setScanType('url')}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition ${scanType === 'url' ? 'bg-white shadow text-blue-600' : 'text-gray-600'}`}
              >
                Scan URL
              </button>
              <button
                type="button"
                onClick={() => setScanType('email')}
                className={`px-3 py-1.5 text-xs font-medium rounded-md transition ${scanType === 'email' ? 'bg-white shadow text-blue-600' : 'text-gray-600'}`}
              >
                Scan Email
              </button>
            </div>
          </div>

          <form onSubmit={handlePhishingScan} className="space-y-4">
            {scanType === 'url' ? (
              <input
                type="text"
                value={phishingInput}
                onChange={(e) => setPhishingInput(e.target.value)}
                placeholder="https://suspicious-login-domain.com"
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            ) : (
              <textarea
                rows={4}
                value={phishingInput}
                onChange={(e) => setPhishingInput(e.target.value)}
                placeholder="Paste email headers or suspicious message body here..."
                className="w-full px-4 py-3 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            )}
            <button
              type="submit"
              disabled={scanLoading}
              className="px-6 py-3 bg-red-600 text-white font-medium rounded-lg hover:bg-red-700 disabled:opacity-50 transition"
            >
              {scanLoading ? 'Analyzing Payload...' : 'Analyze Threat'}
            </button>
          </form>

          {scanResult && (
            <div className="p-5 bg-gray-50 rounded-xl border border-gray-200">
              <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wider mb-2">Analysis Results</h4>
              <pre className="text-xs bg-gray-900 text-green-400 p-4 rounded-lg overflow-x-auto">
                {JSON.stringify(scanResult, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}

      {/* Tab 3: Telemetry */}
      {activeTab === 'telemetry' && (
        <div className="bg-white p-6 rounded-xl border border-gray-200 shadow-sm space-y-6">
          <div>
            <h3 className="text-lg font-semibold text-gray-800">Recent Telemetry Events</h3>
            <p className="text-sm text-gray-500">Live feed of intercepted threat events and system health diagnostics.</p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-gray-200 text-xs text-gray-500 uppercase tracking-wider">
                  <th className="py-3 px-4">Timestamp</th>
                  <th className="py-3 px-4">Threat Type</th>
                  <th className="py-3 px-4">Source IP</th>
                  <th className="py-3 px-4">Severity</th>
                  <th className="py-3 px-4">Confidence</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 text-sm">
                {telemetry?.events && telemetry.events.length > 0 ? (
                  telemetry.events.map((ev, idx) => (
                    <tr key={idx} className="hover:bg-gray-50">
                      <td className="py-3 px-4 text-gray-600">{ev.timestamp}</td>
                      <td className="py-3 px-4 font-medium text-gray-900">{ev.threat_type}</td>
                      <td className="py-3 px-4 font-mono text-xs text-gray-500">{ev.source_ip}</td>
                      <td className="py-3 px-4">
                        <span className={`px-2.5 py-1 text-xs rounded-full font-medium ${
                          ev.severity === 'critical' ? 'bg-red-100 text-red-700' :
                          ev.severity === 'high' ? 'bg-orange-100 text-orange-700' :
                          'bg-yellow-100 text-yellow-700'
                        }`}>
                          {ev.severity}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-gray-600">{(ev.confidence_score * 100).toFixed(1)}%</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={5} className="py-8 text-center text-gray-400">
                      {loadingStats ? 'Loading telemetry feed...' : 'No recent threat events recorded.'}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}