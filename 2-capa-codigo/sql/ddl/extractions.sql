CREATE TABLE IF NOT EXISTS `raw.extractions` (
  extraction_id INT64     NOT NULL,
  run_at        TIMESTAMP NOT NULL,
  task          STRING    NOT NULL,
  endpoint      STRING,
  page_number   INT64     NOT NULL,
  has_more      BOOL      NOT NULL,
  cursor        STRING,
  code          INT64     NOT NULL,
  message       STRING,
  result        STRING    NOT NULL
)
PARTITION BY TIMESTAMP_TRUNC(run_at, MONTH)
CLUSTER BY task
OPTIONS (require_partition_filter = FALSE);
