run:
	uvicorn backend.main:app --reload

test:
	pytest

lint:
	ruff check .

format:
	black .

docker:
	docker compose up

# --- Extended Commands ---

evals:
	python evals/run_evals.py

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

docker-build:
	docker compose build --no-cache

docker-down:
	docker compose down