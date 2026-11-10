from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from adforge_renderer import api
from adforge_renderer.database import DatabaseConfig
from adforge_renderer.database.engine import session_transaction
from adforge_renderer.identity import (
    ClerkVerificationConfig,
    VerifiedClerkPrincipal,
    get_clerk_verification_config,
)
from adforge_renderer.project_service import get_or_create_internal_user_id


ISSUER = "https://spotloom-test.clerk.accounts.dev"
PARTY = "http://localhost:3000"
AUDIENCE = "spotloom-api"
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_KEY = PRIVATE_KEY.public_key()


def _token(subject: str = "user_test_subject") -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "iss": ISSUER,
            "sub": subject,
            "aud": AUDIENCE,
            "azp": PARTY,
            "sid": "sess_project_test",
            "iat": now,
            "nbf": now - timedelta(seconds=1),
            "exp": now + timedelta(minutes=2),
        },
        PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": "project-test-key"},
    )


@pytest.fixture
def database_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _disable_sqlite_legacy_transaction_control(dbapi_connection, _connection_record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _begin_sqlite_transaction(connection):
        connection.exec_driver_sql("BEGIN")

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE users (id CHAR(32) PRIMARY KEY, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE external_identities ("
            "id CHAR(32) PRIMARY KEY, issuer TEXT NOT NULL, subject TEXT NOT NULL, "
            "user_id CHAR(32) NOT NULL REFERENCES users(id), "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "CONSTRAINT uq_external_identities_issuer_subject UNIQUE (issuer, subject))"
        )
        connection.exec_driver_sql(
            "CREATE TABLE projects ("
            "id CHAR(32) PRIMARY KEY, owner_user_id CHAR(32) NOT NULL REFERENCES users(id), "
            "name VARCHAR(120) NOT NULL CHECK (length(trim(name)) > 0), "
            "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
            "updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def client(database_factory, monkeypatch):
    config = ClerkVerificationConfig(
        issuer=ISSUER,
        authorized_parties=(PARTY,),
        jwt_public_key=PUBLIC_KEY.public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("ascii"),
        audience=AUDIENCE,
    )

    @contextmanager
    def transaction():
        with session_transaction(database_factory) as session:
            yield session

    def project_session():
        with transaction() as session:
            yield session

    prior_config = api.app.dependency_overrides.get(get_clerk_verification_config)
    prior_session = api.app.dependency_overrides.get(api.get_project_session)
    api.app.dependency_overrides[get_clerk_verification_config] = lambda: config
    api.app.dependency_overrides[api.get_project_session] = project_session
    with TestClient(api.app) as test_client:
        yield test_client
    if prior_config is None:
        api.app.dependency_overrides.pop(get_clerk_verification_config, None)
    else:
        api.app.dependency_overrides[get_clerk_verification_config] = prior_config
    if prior_session is None:
        api.app.dependency_overrides.pop(api.get_project_session, None)
    else:
        api.app.dependency_overrides[api.get_project_session] = prior_session


def _auth(subject: str = "user_test_subject") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(subject)}"}


def test_identity_mapping_is_stable_for_repeated_exact_pair(database_factory) -> None:
    principal = VerifiedClerkPrincipal(issuer=ISSUER, subject="stable-subject")
    with session_transaction(database_factory) as session:
        first = get_or_create_internal_user_id(session, principal)
    with session_transaction(database_factory) as session:
        second = get_or_create_internal_user_id(session, principal)

    assert first == second
    assert isinstance(first, UUID)


def test_duplicate_identity_mapping_does_not_create_second_user(database_factory) -> None:
    principal = VerifiedClerkPrincipal(issuer=ISSUER, subject="duplicate-subject")
    with session_transaction(database_factory) as session:
        first = get_or_create_internal_user_id(session, principal)
        second = get_or_create_internal_user_id(session, principal)
        assert first == second
        assert session.scalar(text("SELECT count(*) FROM users")) == 1
        assert session.scalar(text("SELECT count(*) FROM external_identities")) == 1


def test_project_create_derives_owner_and_trims_name(client) -> None:
    response = client.post("/projects", json={"name": "  Northstar  "}, headers=_auth())

    assert response.status_code == 201
    body = response.json()
    assert UUID(body["id"])
    assert body["name"] == "Northstar"
    assert set(body) == {"id", "name", "created_at", "updated_at"}


def test_project_list_and_get_are_owner_scoped(client) -> None:
    own = client.post("/projects", json={"name": "Mine"}, headers=_auth("owner"))
    other = client.post("/projects", json={"name": "Other"}, headers=_auth("other"))
    own_id = own.json()["id"]
    other_id = other.json()["id"]

    listing = client.get("/projects", headers=_auth("owner"))
    assert listing.status_code == 200
    assert [project["id"] for project in listing.json()] == [own_id]
    assert client.get(f"/projects/{own_id}", headers=_auth("owner")).status_code == 200

    forbidden = client.get(f"/projects/{own_id}", headers=_auth("other"))
    missing = client.get(f"/projects/{uuid4()}", headers=_auth("other"))
    assert forbidden.status_code == missing.status_code == 404
    assert forbidden.json() == missing.json() == {"detail": "Project not found."}
    assert client.get(f"/projects/{other_id}", headers=_auth("owner")).status_code == 404


def test_postgresql_project_ownership_isolation_on_disposable_spotloom_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify owner scoping through the API against an isolated PostgreSQL schema."""
    raw_url = os.environ.get("SPOTLOOM_TEST_DATABASE_URL")
    if not raw_url:
        pytest.skip("Set SPOTLOOM_TEST_DATABASE_URL to the disposable local spotloom_test database.")

    try:
        database_config = DatabaseConfig.from_url(raw_url)
    except ValueError as exc:
        pytest.fail(f"Invalid SPOTLOOM_TEST_DATABASE_URL configuration: {type(exc).__name__}")
    if database_config.url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("Project ownership integration tests require a loopback database host.")
    if database_config.url.database != "spotloom_test":
        pytest.fail("Project ownership integration tests require database spotloom_test.")

    backend_dir = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(backend_dir / "alembic.ini"))
    schema = f"spotloom_project_owner_test_{uuid4().hex}"
    admin_engine = create_engine(database_config.url, hide_parameters=True, pool_pre_ping=True)
    worker_engine = None
    prior_config = api.app.dependency_overrides.get(get_clerk_verification_config)
    prior_session = api.app.dependency_overrides.get(api.get_project_session)

    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.commit()
            connection.exec_driver_sql(f'SET search_path TO "{schema}"')
            connection.commit()
            alembic_config.attributes["connection"] = connection
            command.upgrade(alembic_config, "head")

        worker_engine = create_engine(
            database_config.url,
            hide_parameters=True,
            pool_pre_ping=True,
        )

        @event.listens_for(worker_engine, "connect")
        def _set_isolated_schema(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute(f'SET search_path TO "{schema}"')
            cursor.close()

        factory = sessionmaker(bind=worker_engine, autoflush=False, expire_on_commit=False)

        @contextmanager
        def transaction():
            with session_transaction(factory) as session:
                yield session

        def project_session():
            with transaction() as session:
                yield session

        verification_config = ClerkVerificationConfig(
            issuer=ISSUER,
            authorized_parties=(PARTY,),
            jwt_public_key=PUBLIC_KEY.public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ).decode("ascii"),
            audience=AUDIENCE,
        )
        api.app.dependency_overrides[get_clerk_verification_config] = lambda: verification_config
        api.app.dependency_overrides[api.get_project_session] = project_session

        with TestClient(api.app) as test_client:
            user_a = _auth("postgres-owner-a")
            user_b = _auth("postgres-owner-b")
            created = test_client.post("/projects", json={"name": "Owner A project"}, headers=user_a)
            assert created.status_code == 201
            project_id = created.json()["id"]

            user_b_projects = test_client.get("/projects", headers=user_b)
            assert user_b_projects.status_code == 200
            assert user_b_projects.json() == []
            assert test_client.get(f"/projects/{project_id}", headers=user_b).status_code == 404

            owner_read = test_client.get(f"/projects/{project_id}", headers=user_a)
            assert owner_read.status_code == 200
            assert owner_read.json()["id"] == project_id

            forged = test_client.post(
                "/projects",
                json={"name": "Forged ownership", "owner_user_id": "attacker-controlled"},
                headers=user_b,
            )
            assert forged.status_code == 422
            assert test_client.get("/projects", headers=user_b).json() == []
    finally:
        if prior_config is None:
            api.app.dependency_overrides.pop(get_clerk_verification_config, None)
        else:
            api.app.dependency_overrides[get_clerk_verification_config] = prior_config
        if prior_session is None:
            api.app.dependency_overrides.pop(api.get_project_session, None)
        else:
            api.app.dependency_overrides[api.get_project_session] = prior_session
        alembic_config.attributes.pop("connection", None)
        if worker_engine is not None:
            worker_engine.dispose()
        try:
            with admin_engine.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        finally:
            admin_engine.dispose()


@pytest.mark.parametrize("method,path,body", [
    ("get", "/projects", None),
    ("post", "/projects", {"name": "No auth"}),
    ("get", f"/projects/{uuid4()}", None),
])
def test_project_routes_reject_unauthenticated_requests(client, method, path, body) -> None:
    response = getattr(client, method)(path, json=body) if body is not None else getattr(client, method)(path)
    assert response.status_code == 401


@pytest.mark.parametrize("field", ["owner_id", "owner_user_id", "user_id", "issuer", "subject"])
def test_client_identity_and_ownership_fields_are_rejected(client, field) -> None:
    response = client.post(
        "/projects",
        json={"name": "Rejected", field: "attacker-controlled"},
        headers=_auth(),
    )
    assert response.status_code == 422
    assert client.get("/projects", headers=_auth()).json() == []


@pytest.mark.parametrize("payload", [{}, {"name": ""}, {"name": " \t\n "}, {"name": "x" * 121}])
def test_project_name_is_required_nonblank_and_bounded(client, payload) -> None:
    response = client.post("/projects", json=payload, headers=_auth())
    assert response.status_code == 422


def test_project_create_rejects_extra_identity_fields_without_reflection(client) -> None:
    response = client.post(
        "/projects", json={"name": "Safe", "subject": "do-not-reflect"}, headers=_auth()
    )
    assert response.status_code == 422
    assert "do-not-reflect" not in response.text


def test_identity_mapping_rolls_back_with_outer_transaction(database_factory) -> None:
    principal = VerifiedClerkPrincipal(issuer=ISSUER, subject="rollback-subject")
    with pytest.raises(RuntimeError):
        with session_transaction(database_factory) as session:
            get_or_create_internal_user_id(session, principal)
            raise RuntimeError("rollback test")
    with session_transaction(database_factory) as session:
        assert session.scalar(text("SELECT count(*) FROM users")) == 0
        assert session.scalar(text("SELECT count(*) FROM external_identities")) == 0
