"""The reporting builder: ``/report`` endpoints. These routes act for the caller, so they
require the gateway token (a request without one gets a clean 401 instead of a broken
``Bearer `` header on the Mistral API call)."""

from fastapi import HTTPException, params
from utils.mistral import MistralNotConfiguredError, caller_credentials


def _require_caller() -> None:
    creds = None
    try:
        creds = caller_credentials()
    except MistralNotConfiguredError:
        creds = None
    if creds is None or not creds.token:
        raise HTTPException(status_code=401, detail="Authentification requise : aucun token gateway sur la requête.")


dependencies: tuple[params.Depends, ...] = (params.Depends(_require_caller),)
