"""Batch runner.

Applies core.convert_image() to a set of uploaded files and collects
a summary report (processed / skipped / errored) instead of letting a
single bad file crash the run. Used by the web app's multi-file
upload handler.
"""
