-- Runs only the first time the Postgres volume is created.
-- The test suite truncates tables, so it must never share a database with development data.
CREATE DATABASE flowops_test;
