#!/bin/bash -e

./manage.py wait_for_resources --db --celery-broker

celery -A main worker \
    -l INFO \
    -Q "${CELERY_QUEUES:-default,report-llm}" \
    --concurrency 1 \
    --max-tasks-per-child 4
