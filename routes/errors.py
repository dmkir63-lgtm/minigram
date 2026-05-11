from flask import jsonify

from extensions import app


@app.errorhandler(429)
def handle_rate_limit(error):
    retry_after = getattr(error, "retry_after", None)
    message = "Слишком много запросов. Попробуйте позже."
    response = jsonify(
        {
            "ok": False,
            "error": message,
            "retry_after": retry_after,
        }
    )
    response.status_code = 429
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return response
