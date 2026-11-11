"""OIDC identity is the ownership boundary in multi-user deployments."""
import hashlib
import os


def required():
    return os.environ.get("SYSDESIGN_REQUIRE_AUTH", "false").lower() == "true"


def identity_key(claims):
    issuer, subject = claims.get("iss"), claims.get("sub")
    if not isinstance(issuer, str) or not issuer or not isinstance(subject, str) or not subject:
        raise ValueError("The identity provider must supply issuer and subject claims.")
    return hashlib.sha256((issuer + "\0" + subject).encode()).hexdigest()[:32]


def enforce_login():
    if not required():
        return
    import streamlit as st
    if not st.user.get("is_logged_in", False):
        st.title("System design lab")
        st.write("Sign in to run experiments and access your saved designs.")
        if st.button("Sign in", type="primary"):
            st.login()
        st.stop()
    try:
        identity_key(st.user)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
    with st.sidebar:
        st.caption(f"Signed in as {st.user.get('name', 'user')}")
        if st.button("Sign out"):
            st.logout()
