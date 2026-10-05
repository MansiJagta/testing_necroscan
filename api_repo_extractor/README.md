# NecroScan Repository API Extractor

This is a small, self-contained MVP module for the API Guardian Hub / Zombie API Defence project.

It accepts a public GitHub repository URL, clones the repository, discovers APIs from source code, extracts APIs from OpenAPI/Swagger files when present, and returns a unified API inventory.

## Supported source patterns

- FastAPI
- Flask
- Django URL patterns
- Express.js
- Spring Boot

## Important limitation

A GitHub repository only gives static/source evidence.

This module does NOT invent runtime traffic.

When runtime traffic is unavailable:

```text
runtime_data_available = false
usage_status = UNKNOWN
```

Therefore, this module should not claim an API is Zombie merely because no runtime information was supplied.

## Add to an existing FastAPI application

Copy the `repo_api_extractor` folder into your backend.

Then in your main FastAPI application:

```python
from repo_api_extractor.router import router as repository_router

app.include_router(repository_router)
```

If your `main.py` is under another package, use the equivalent import path.

## Run

Make sure Git is installed in the environment where the backend runs.

Then start your FastAPI application normally.

## Test

Request:

```http
POST /api/repository/scan
Content-Type: application/json

{
  "repo_url": "https://github.com/owner/repository"
}
```

The response contains:

- detected frameworks
- source API count
- documented API count
- unified inventory
- HTTP method
- path
- source file
- line number
- documentation status
- runtime-data availability
- initial classification state

## Docker note

Because your API Guardian Hub runs the backend in Docker, Git must exist inside the backend/worker image if repository cloning is performed there.

Check with:

```bash
git --version
```

inside the relevant container.

If Git is missing, add Git to the Docker image rather than installing Celery on Windows.
