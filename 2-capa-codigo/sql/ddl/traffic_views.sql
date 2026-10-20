CREATE TABLE IF NOT EXISTS `raw.traffic_views` (
  extraction_id INT64     NOT NULL,
  run_at        TIMESTAMP NOT NULL,
  task          STRING    NOT NULL,
  page_number   INT64     NOT NULL,
  repo_id       INT64     NOT NULL,
  timestamp     TIMESTAMP NOT NULL,
  count         INT64,
  uniques       INT64
)
PARTITION BY TIMESTAMP_TRUNC(run_at, MONTH)
CLUSTER BY task
OPTIONS (require_partition_filter = FALSE);
