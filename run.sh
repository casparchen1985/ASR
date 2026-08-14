#!/bin/bash
cd "$(dirname "$0")"
exec scripts/asr_pipeline/.venv/bin/python3 scripts/asr_pipeline/phase1_pipeline.py "$@"
