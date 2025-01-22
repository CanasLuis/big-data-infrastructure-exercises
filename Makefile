.PHONY: \
	build \
	run \
	deploy \
	run_local \
	test \
	test_api \
	logs \

.DEFAULT_GOAL:=help

SHELL=bash

export DOCKER_REPOSITORY=XXXX.dkr.ecr.us-east-1.amazonaws.com
export DOCKER_FILE=${DOCKER_FILE_OW:-"docker/Dockerfile"}
DOCKER_COMPOSE_FILE := ${DOCKER_COMPOSE_FILE-docker/compose.yaml}

compose_file = compose.yaml
service = bdi-api
image_name = $(service)# ${DOCKER_REPOSITORY}/${SERVICE_NAME}
tag = $(shell poetry version -s)

export SERVICE_NAME=$(poetry version | awk '{print $$1}')
export IMAGE_NAME=${SERVICE_NAME}  # ${DOCKER_REPOSITORY}/${SERVICE_NAME}
export GIT_REPO=$(shell git config --get remote.origin.url | sed -E 's/^\s*.*:\/\///g')
export GIT_COMMIT=$(shell git rev-parse HEAD)

run:
    uvicorn bdi_api.app:app --proxy-header --host 0.0.0.0 --port 8080

test:
	pytest -cov=bdi_api --cov-report=html

build:
	@echo "Building image $(service):$(tag) from $(compose_file)"
	IMAGE_TAG="$(tag)" IMAGE_NAME=$(image_name) docker compose -f docker/$(compose_file) build $(service)
	docker tag "$(image_name)":"$(tag)" "$(image_name)":latest

build_docker:
	@echo "Building image $(service):$(tag) from docker/Dockerfile"
    docker build -t bdi_api:latest -f docker/Dockerfile .

monitoring:
	docker compose -f docker/monitor/uptrace.yaml up -d


run_docker: build
	IMAGE_TAG="$(tag)" IMAGE_NAME=$(image_name) docker compose -f docker/$(compose_file) stop
	IMAGE_TAG="$(tag)" IMAGE_NAME=$(image_name) docker compose -f docker/$(compose_file) up -d
	@echo "You can check now http://localhost:8080/docs"

stop_docker:
	IMAGE_TAG="$(tag)" IMAGE_NAME=$(image_name) docker compose -f docker/$(compose_file) stop


ps:
	IMAGE_TAG="$(tag)" IMAGE_NAME=$(image_name) docker compose -f docker/$(compose_file) ps

test_api: run_local
	st run --checks all http://localhost:8080/openapi.json -H "Authorization: Bearer TOKEN"

logs:
	IMAGE_TAG="$(tag)" IMAGE_NAME=$(image_name) docker compose -f docker/$(compose_file) logs $(service)

config:
	docker compose -f ${DOCKER_COMPOSE_FILE} config
