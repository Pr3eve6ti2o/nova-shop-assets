.PHONY: help install run test lint docker-build docker-up docker-down

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

install: ## Install bot dependencies into the current environment
	pip install -r bot/requirements.txt

run: ## Run the bot (polling by default)
	cd bot && python app.py

doctor:
	python3 tools/doctor.py

test: ## Run the test suite
	python -m pytest bot/tests -q

lint: ## Lint with ruff
	ruff check bot

docker-build: ## Build the Docker image
	docker build -t nova-shop-bot .

docker-up: ## Start the bot with docker compose
	docker compose up -d

docker-down: ## Stop the docker compose stack
	docker compose down

seed: ## Seed a demo database (DATABASE_PATH or bot/data/demo.db)
	python3 tools/seed_demo.py

smoke: ## Run offline smoke checks
	python3 tools/smoke.py

usability: ## Run the usability smoke (fake Telegram API journey)
	python3 tools/usability_smoke.py
