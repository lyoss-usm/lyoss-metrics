CREATE TABLE IF NOT EXISTS `raw.users` (
  extraction_id INT64     NOT NULL,
  run_at        TIMESTAMP NOT NULL,
  task          STRING    NOT NULL,
  page_number   INT64     NOT NULL,
  id            INT64     NOT NULL,
  login         STRING,
  type          STRING
)
PARTITION BY TIMESTAMP_TRUNC(run_at, MONTH)
CLUSTER BY task
OPTIONS (require_partition_filter = FALSE);
