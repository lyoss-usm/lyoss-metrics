CREATE TABLE IF NOT EXISTS `raw.commits` (
  extraction_id INT64     NOT NULL,
  run_at        TIMESTAMP NOT NULL,
  task          STRING    NOT NULL,
  page_number   INT64     NOT NULL,
  sha           STRING    NOT NULL,
  repo_id       INT64     NOT NULL,
  user_login    STRING,
  commit_date   TIMESTAMP
)
PARTITION BY TIMESTAMP_TRUNC(run_at, MONTH)
CLUSTER BY task
OPTIONS (require_partition_filter = FALSE);
