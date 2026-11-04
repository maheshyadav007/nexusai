"""Verified HTTPS using native certificate stores, including managed enterprise roots."""

import os
import ssl

import truststore


def system_ssl_context() -> ssl.SSLContext:
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # Optional additional roots augment, rather than replace, the operating-system store.
    if extra := os.environ.get("SSL_CERT_FILE"):
        context.load_verify_locations(cafile=extra)
    return context
