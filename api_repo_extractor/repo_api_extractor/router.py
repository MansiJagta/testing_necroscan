from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, HttpUrl

from .scanner import scan_repository

router = APIRouter(prefix="/api/repository", tags=["Repository API Discovery"])


class RepositoryScanRequest(BaseModel):
    repo_url: HttpUrl


@router.post("/scan")
def scan_repo(request: RepositoryScanRequest):
    """
    Demo/MVP endpoint:
    POST a public GitHub repository URL and receive discovered APIs.
    """
    try:
        return scan_repository(str(request.repo_url))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Repository scan failed: {exc}"
        )
