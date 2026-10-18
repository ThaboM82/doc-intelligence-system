# Document Intelligence & Security Platform

**Enterprise document ingestion · vector search · citation-backed RAG**

Enterprise-grade document intelligence platform combining secure ingestion, vector search, citation-backed retrieval, and operational governance.

| | | |
|--|--|--|
| 🐍 Python 3.10+ | ⚡ FastAPI | ⚛️ React |
| 🗄️ Qdrant | 🧠 OpenAI | 🚀 Render · ▲ Vercel |
| 🏗️ Layered architecture | 📚 Citation-backed RAG | 🛡️ Security-first |

| Layer | Stack | Host |
|-------|--------|------|
| 🔌 API | FastAPI · LangChain · OpenAI | Render |
| 🗄️ Vectors | Qdrant Cloud (cosine, 1536-dim) | Qdrant |
| 🖥️ UI | React · Vite · Tailwind · Lucide | Vercel |
| 📦 Version | API 1.5.x | — |

## 🏗️ Solution structure

This repository is organized as a layered enterprise system: presentation, API, intelligence, data, security, and infrastructure—each with a clear responsibility boundary.

## 💡 Why this project matters

Organizations sit on large volumes of policies, contracts, runbooks, incident reports, and product docs. That knowledge is often locked in shared drives and PDFs, so people search manually, ask the same questions repeatedly, or make decisions without the latest approved text.

**Document Intelligence & Security Platform** turns those files into a controlled, searchable knowledge layer:

| Challenge | How this platform helps |
|-----------|-------------------------|
| 📂 Knowledge is scattered across files | Ingest once; retrieve by meaning (RAG), not only keywords |
| ✅ Answers must be trustworthy | Responses are grounded in retrieved document chunks with source citations |
| ⚠️ Security and compliance risk | Pre-index security scanning, upload limits, admin controls, audit-oriented ops endpoints |
| 🚫 Shadow IT chat tools on sensitive docs | Keep data paths explicit: your API, your Qdrant, your OpenAI project |
| 🐢 Slow onboarding and support | Staff query internal procedures in seconds instead of hunting through folders |

This is not a generic chatbot. It is an enterprise document RAG system designed for accuracy, traceability, and governance.

## 🧩 Platform architecture

```text
┌────────────────────────────────────────────────────────────┐
│                    Presentation Layer                       │
│  React · Vite · Tailwind                                   │
│  Upload · Search · Chat · Citations · Admin Dashboard      │
└───────────────────────────┬────────────────────────────────┘
                            │ HTTPS / CORS
                            ▼
┌────────────────────────────────────────────────────────────┐
│                         API Layer                           │
│  FastAPI · Validation · Security Controls                  │
│  Rate Limiting · Health Checks · Admin Operations          │
└───────────────────────────┬────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│                    Intelligence Layer                       │
│  Extraction · Chunking · Embeddings · RAG                  │
│  Retrieval · Citations · Context Assembly                  │
└───────────────────────────┬────────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
┌──────────────────┐            ┌──────────────────┐
│ OpenAI           │            │ Qdrant Cloud     │
│ Embeddings + LLM │            │ Vector Database  │
└──────────────────┘            └──────────────────┘

🔄 Document lifecycle
Every document follows a controlled pipeline designed for security, traceability, and retrieval accuracy.
📄 Upload
  → ✅ Validation
  → 🛡️ Security Scan
  → 📖 Text Extraction
  → ✂️ Chunking
  → 🧠 Embedding Generation
  → 🗄️ Qdrant Indexing
  → 🔍 Semantic Retrieval
  → 📚 Citation Assembly
  → 💬 Grounded Answer

🎯 Business capability mapping
Business need                   Platform capability
📄 Secure document onboarding  Upload validation and security scanning
🔍 Fast knowledge discovery    Vector search and semantic retrieval
✅ Trustworthy answers         RAG with source citations                                 📊 Auditability                Metadata tracking and provenance
🏛️ Governance                  Administrative controls and operational endpoints
👥 Employee self-service       Natural-language document sear                             ⚡ Faster onboarding           Searchable internal knowledge corpus 
🛡️ Compliance readiness        Controlled document lifecycle 

📁 Repository structure
doc-intelligence-system/
├── .github/workflows/           # CI tests, eval gates, deploy hooks
├── backend/                     # FastAPI application
│   ├── main.py                  # Entrypoint: lifespan, middleware, probes
│   ├── routers/                 # Canonical HTTP API
│   │   ├── ingestion.py         # Document upload
│   │   ├── documents.py         # List / get / delete
│   │   ├── rag.py               # RAG query
│   │   ├── auth.py
│   │   ├── admin.py
│   │   └── intelligence.py
│   ├── services/                # Domain logic
│   │   ├── ingest_service.py
│   │   ├── embeddings.py
│   │   └── rag_service.py
│   ├── security/                # Scanning + validators (RBAC, injection)
│   ├── observability/           # cost, metrics, tracing
│   ├── db/                      # Qdrant client + optional SQL
│   ├── core/                    # Shared config / telemetry helpers
│   ├── data/                    # Samples, eval sets, local uploads
│   ├── evaluation/              # Eval harness helpers
│   ├── models/                  # LLM factory and related models
│   ├── ingestion/               # Alternate/legacy pipeline modules
│   └── api/                     # Legacy scaffolds (prefer routers/)
├── frontend/                    # React + Vite UI (Vercel root)
│   └── src/
│       ├── App.tsx
│       ├── components/          # Upload, RAG chat, security, admin, login
│       └── lib/apiClient.ts
├── evals/
│   └── run_evals.py             # CLI evaluation against API
├── tests/                       # pytest suites
├── scripts/                     # Operational utilities
├── config/                      # Shared configuration assets
├── docker-compose.yml           # Local orchestration
├── docker-compose.override.yml  # Local overrides (optional)
├── requirements.txt             # Production Python dependencies
├── requirements-ml.txt          # Local heavy ML / Docling only
├── pyproject.toml
├── Makefile                     # Common operational commands
└── README.md

🔐 Environment variables
Backend (Render / local .env)

Variable             Required       Description                       OPENAI_API_KEY       ✅ Yes         Embeddings and chat
QDRANT_URL           ✅ Yes         Cluster endpoint
QDRANT_API_KEY       ✅ Yes(Cloud)  Qdrant API key
QDRANT_COLLECTION    ⚪ No          Default document_intelligence
QDRANT_VECTOR_SIZE   ⚪ No          Default 1536
CORS_ORIGINS         ✅ Yes (prod)  Comma-separated allowed origins
ADMIN_API_KEY /      ⭐             Admin route protection 
ADMIN_API_TOKEN       Recommended  
ENVIRONMENT          ⭐             Use production in live deployment
                      Recommended 
LANGSMITH_TRACING    ⚪ Optional    Enable with LANGSMITH_API_KEY

📄 License
Proprietary / internal use unless otherwise specified by the repository owner.
📦 Repository: https://github.com/ThaboM82/doc-intelligence-system
