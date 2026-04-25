FLASK_APP_PY := run.py
DEPLOYMENT_PATH := ./mcp_deployment/
DOCKER_COMPOSE_FILE := $(DEPLOYMENT_PATH)docker-compose-prod.yml
DOCKER_COMPOSE_FILE_DEV := $(DEPLOYMENT_PATH)docker-compose-dev.yml
DOCKER_SERVICE_NAME := mcp_testcase_service
DOCKER_IMAGE_TAG := $(DOCKER_SERVICE_NAME):latest

.DEFAULT_GOAL := help

.PHONY: help
help:
	@echo "Available commands:"
	@echo "  make run-dev-docker        - NA"
	@echo "  make run-prod              - NA"


.PHONY: run-dev-docker
run-dev-docker:
	@echo "========== Starting Docker Compose Process =========="
	@echo "========== 1. Stopping and removing containers, and cleaning up unused images =========="
	docker-compose -f $(DOCKER_COMPOSE_FILE_DEV) down --remove-orphans
	docker image prune -f
	@echo "========== 2. Building and starting the Docker service ($(DOCKER_SERVICE_NAME)) =========="
	docker-compose -f $(DOCKER_COMPOSE_FILE_DEV) build --no-cache
	docker-compose -f $(DOCKER_COMPOSE_FILE_DEV) up -d
	@echo "========== 3. Checking the status of the Docker service ($(DOCKER_SERVICE_NAME)) =========="
	docker-compose -f $(DOCKER_COMPOSE_FILE_DEV) ps
	docker image prune -f
	docker rmi $(DOCKER_IMAGE_TAG) || echo "⚠️ Image not found or in use"
	@echo "========== Docker Compose Process Complete =========="

.PHONY: run-prod
run-prod:
	@echo "========== Starting Docker Compose Process =========="
	@echo "========== 1. Stopping and removing containers, and cleaning up unused images =========="
	docker-compose -f $(DOCKER_COMPOSE_FILE) down --remove-orphans
	docker image prune -f
	@echo "========== 2. Building and starting the Docker service ($(DOCKER_SERVICE_NAME)) =========="
	docker-compose -f $(DOCKER_COMPOSE_FILE) build --no-cache
	docker-compose -f $(DOCKER_COMPOSE_FILE) up -d
	@echo "========== 3. Checking the status of the Docker service ($(DOCKER_SERVICE_NAME)) =========="
	docker-compose -f $(DOCKER_COMPOSE_FILE) ps
	docker image prune -f
	docker rmi $(DOCKER_IMAGE_TAG) || echo "⚠️ Image not found or in use"
	@echo "========== Docker Compose Process Complete =========="