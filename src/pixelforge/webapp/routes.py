"""Flask routes.

Planned:
    GET  /             -> upload form (format, size, resize-mode,
                            rotate controls)
    POST /api/convert  -> accepts multiple uploaded files, runs the
                            batch engine, returns a downloadable ZIP
                            of converted images
"""
