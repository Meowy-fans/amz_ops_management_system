# Database Migrations

This directory contains Alembic migration scripts for managing the database schema.

## Setup

1. Make sure you have the dependencies installed:
   ```bash
   pip install -r requirements.txt
   ```

2. Make sure your `.env` file is configured with the correct database credentials.

## Usage

### Applying Migrations

To apply all pending migrations to the database:
```bash
alembic upgrade head
```

### Creating a New Migration

To create a new migration script (e.g., after modifying the schema):
```bash
alembic revision -m "description_of_change"
```
*Note: Since the project currently uses raw SQL and not SQLAlchemy ORM models, `autogenerate` is not available. You must manually write the `upgrade()` and `downgrade()` logic in the generated file.*

### Rolling Back

To revert the last migration:
```bash
alembic downgrade -1
```

## Structure

- `versions/`: Contains the migration scripts.
- `env.py`: Configuration script that sets up the Alembic environment.
- `script.py.mako`: Template for new migration scripts.
- `../alembic.ini`: Main configuration file (in project root).
