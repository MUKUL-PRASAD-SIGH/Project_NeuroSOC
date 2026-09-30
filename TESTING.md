# NeuroSOC Local Testing Guide

This guide provides instructions for sequentially testing the entire NeuroSOC platform locally using the CLI. The test suite has been structured for progressive validation.

## Prerequisites

Ensure you have the following installed and configured:
- Python 3.9+
- Docker & Docker Compose
- Node.js (for frontend testing)
- `pytest` for running Python test suites

## Test Directory Structure

The `tests/` directory is organized into logical, sequential stages:

1. **`01_unit/`**: Core functions, models, and stateless logic.
2. **`02_integration/`**: Cross-service communication, database models, Kafka queues.
3. **`03_e2e/`**: Full platform workflows and end-to-end API tests.

## Running Tests Locally

To validate the platform, run these steps in order.

### Step 1: Unit Tests
Validate the core logic and standalone functions.
```bash
pytest tests/01_unit/ -v
```

### Step 2: Integration Tests
Ensure services like Kafka, Redis, and internal APIs communicate correctly. 
*Note: Make sure your local Docker services (Redis, Kafka, DB) are running.*
```bash
docker-compose up -d redis kafka postgres
pytest tests/02_integration/ -v
```

### Step 3: End-to-End (E2E) Tests
Test complete end-to-end user journeys and system interactions.
```bash
# Ensure all services are up
docker-compose up -d
pytest tests/03_e2e/ -v
```

### Run All Tests
To run the entire test suite sequentially:
```bash
pytest tests/ -v --order-dependencies
```

## Troubleshooting
- **Missing modules**: Make sure you activate your virtual environment and run `pip install -r requirements.txt`.
- **Connection Refused**: Ensure `docker-compose up -d` has successfully started the required backing services before running integration and E2E tests.
