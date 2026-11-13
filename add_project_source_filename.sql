-- Optional manual fallback; the app adds this column automatically if missing.
ALTER TABLE projects
ADD COLUMN source_filename VARCHAR(255) NULL;
