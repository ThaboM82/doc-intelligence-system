import { useState } from "react";
import {
  Shield,
  Play,
  RefreshCw,
} from "lucide-react";

const ThreatScanner = () => {
  const [progress, setProgress] =
    useState(76);

  const startScan = () => {
    setProgress(0);

    const timer = setInterval(() => {
      setProgress((prev) => {
        if (prev >= 100) {
          clearInterval(timer);

          return 100;
        }

        return prev + 5;
      });
    }, 300);
  };

  return (
    <div className="analytics-card">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-xl font-semibold">
          Security Scanner
        </h3>

        <Shield
          size={24}
          className="text-blue-600"
        />
      </div>

      <div className="space-y-5">
        <div>
          <div className="mb-2 flex justify-between">
            <span>Progress</span>
            <span>{progress}%</span>
          </div>

          <div className="progress-track">
            <div
              className="progress-fill"
              style={{
                width: `${progress}%`,
              }}
            />
          </div>
        </div>

        <div className="rounded-xl border border-slate-200 p-4 dark:border-slate-700">
          <h4 className="font-semibold">
            Scanner Status
          </h4>

          <p className="mt-2 text-sm text-slate-500">
            Monitoring uploads,
            documents and API
            submissions in real-time.
          </p>
        </div>

        <div className="flex gap-3">
          <button
            onClick={startScan}
            className="btn-primary flex-1"
          >
            <Play size={18} />
            Start Scan
          </button>

          <button className="btn-secondary">
            <RefreshCw size={18} />
          </button>
        </div>
      </div>
    </div>
  );
};

export default ThreatScanner;