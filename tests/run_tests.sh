#!/bin/bash
# Run unit tests for utils, services, and repositories
# Execute from project root

export PYTHONPATH=$PYTHONPATH:$(pwd)

echo "Running Utils Tests..."
pytest tests/unit/utils/

echo "Running Services Tests..."
pytest tests/unit/services/

echo "Running Repository Tests..."
pytest tests/unit/repositories/
