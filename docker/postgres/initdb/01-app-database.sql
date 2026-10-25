-- Runs once, on the first start of an empty database, as the admin user (standard Postgres image).
-- Creates the app's own login, its database, a separate test database, and pgvector in both.
-- A plain .sql file (not a script), so nothing is executed as a separate program; values come
-- from the container's environment via psql's \getenv. The image stops at the first error.
\getenv app_user APP_DB_USER
\getenv app_password APP_DB_PASSWORD
\getenv app_db APP_DB_NAME

CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password';

CREATE DATABASE :"app_db" OWNER :"app_user";
\connect :"app_db"
CREATE EXTENSION IF NOT EXISTS vector;

-- Separate database for automated tests, so they never touch the app's own data
\connect postgres
CREATE DATABASE imcp_test OWNER :"app_user";
\connect imcp_test
CREATE EXTENSION IF NOT EXISTS vector;
