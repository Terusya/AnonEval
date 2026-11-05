import os

import pytest
from pydantic import ValidationError

os.environ.setdefault("DB_NAME", "test")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("PEPPER_SECRET", "test-pepper")
os.environ.setdefault("APP_INTERNAL_SECRET", "test-internal-secret")
os.environ.setdefault("RABBITMQ_PASSWORD", "test-broker")

from app.security import hash_password, verify_password
from app.survey_main import ResponseCreate, SurveyCreate


def test_password_hash_uses_unique_salts_and_verifies() -> None:
    first_hash, first_salt = hash_password("sample-password", "pepper-secret")
    second_hash, second_salt = hash_password("sample-password", "pepper-secret")

    assert first_salt != second_salt
    assert first_hash != second_hash
    assert verify_password("sample-password", "pepper-secret", first_salt, first_hash)
    assert not verify_password("wrong-password", "pepper-secret", first_salt, first_hash)
    assert not verify_password("sample-password", "other-pepper", first_salt, first_hash)


def test_response_rejects_identity_and_server_owned_fields() -> None:
    with pytest.raises(ValidationError):
        ResponseCreate(
            rating_materials=4,
            rating_clarity=4,
            rating_engagement=4,
            user_id=999,
        )


def test_survey_create_ignores_server_owned_fields() -> None:
    payload = SurveyCreate.model_validate(
        {
            "subject_id": 1,
            "teacher_id": 2,
            "period_start": "2026-09-01",
            "period_end": "2026-12-31",
            "status": "closed",
            "created_by": 999,
            "role": "student",
        }
    )

    assert not hasattr(payload, "status")
    assert not hasattr(payload, "created_by")
    assert not hasattr(payload, "role")
