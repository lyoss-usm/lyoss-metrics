CREATE TABLE IF NOT EXISTS `raw.actions` (
  extraction_id INT64     NOT NULL,
  run_at        TIMESTAMP NOT NULL,
  task          STRING    NOT NULL,
  page_number   INT64     NOT NULL,
  id            INT64     NOT NULL,
  repo_id       INT64     NOT NULL,
  name          STRING,
  status        STRING,
  conclusion    STRING,
  created_at    TIMESTAMP,
  updated_at    TIMESTAMP
)
PARTITION BY TIMESTAMP_TRUNC(run_at, MONTH)
CLUSTER BY task
OPTIONS (require_partition_filter = FALSE);
