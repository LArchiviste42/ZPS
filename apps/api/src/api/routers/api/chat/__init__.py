"""The chat feature: ``route.py`` is ``/chat``, so the endpoint is ``/api/chat``.

The access rule is declared here, cascading to every module in this package. Empty is the
declaration, not an omission: the gateway still authenticates each request and installs the
caller's credential, which the route spends via ``caller_mistral_client``.
"""

from fastapi import params

dependencies: tuple[params.Depends, ...] = ()
