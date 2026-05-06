# Makefile

.PHONY: proto build up down test logs clean help

PROTO_SRC := protos/ai_inference.proto

## Generate gRPC stubs from the .proto file
proto:
	python -m grpc_tools.protoc \
		-I protos \
		--python_out=server \
		--grpc_python_out=server \
		$(PROTO_SRC)
	python -m grpc_tools.protoc \
		-I protos \
		--python_out=client \
		--grpc_python_out=client \
		$(PROTO_SRC)
	@echo "✔  Stubs generated in server/ and client/"

## Build all Docker images
build:
	docker compose build

## Start the full mesh (3 servers + nginx)
up:
	docker compose up -d
	@echo "✔  Mesh is up. Nginx listening on :80"

## Stop and remove containers
down:
	docker compose down

## Run the CLI tester against the live mesh
test:
	docker compose --profile test run --rm client

## Tail logs from all services
logs:
	docker compose logs -f

## Tail only nginx logs
logs-nginx:
	docker compose logs -f nginx

## Run the client locally (requires running mesh)
run-local:
	cd client && GRPC_TARGET=localhost:80 python client.py

## Remove all containers, images, and volumes
clean:
	docker compose down --volumes --rmi all

help:
	@grep -E '^##' Makefile | sed 's/## /  /'
