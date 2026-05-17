#!/usr/bin/env bash
set -euo pipefail

COMPOSE_DIR="${COMPOSE_DIR:-/data/docker-compose/amz-listing-management-system}"
PROJECT_DIR="${PROJECT_DIR:-/home/liangqinhao/amz_listing_management_system}"

if [ ! -f "${COMPOSE_DIR}/docker-compose.yml" ]; then
  echo "Missing ${COMPOSE_DIR}/docker-compose.yml"
  echo "Install the production compose bundle first:"
  echo "  mkdir -p ${COMPOSE_DIR}"
  echo "  cp ${PROJECT_DIR}/deploy/production/docker-compose.yml ${COMPOSE_DIR}/docker-compose.yml"
  echo "  cp ${PROJECT_DIR}/deploy/production/.env.example ${COMPOSE_DIR}/.env"
  exit 1
fi

if [ ! -f "${COMPOSE_DIR}/.env" ]; then
  echo "Missing ${COMPOSE_DIR}/.env; copy .env.example and fill secrets before deploying."
  exit 1
fi

if [ ! -f "${COMPOSE_DIR}/.env.amazon-sp-api" ]; then
  echo "Missing optional ${COMPOSE_DIR}/.env.amazon-sp-api; Amazon SP-API features will fail closed in production."
fi

cd "${COMPOSE_DIR}"
docker compose build
docker compose up -d
docker compose ps
