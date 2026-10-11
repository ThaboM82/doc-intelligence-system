# backend/data

Runtime and reference files for the Document Intelligence API.

## Safe to commit
- sample_docs/, fixtures/, iocs/, policies/, prompts/, README.md

## Do not commit (keep folders, ignore contents)
- uploads/**, cache/**, quarantine/** (except .gitkeep)

## Never store here
- API keys, .env, production PII dumps, live malware samples

Secrets belong in Render / Vercel environment variables only.
