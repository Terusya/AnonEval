import hmac
import secrets

from argon2.low_level import Type, hash_secret_raw


ARGON2_MEMORY_COST = 65536
ARGON2_TIME_COST = 3
ARGON2_PARALLELISM = 4
HASH_LENGTH = 32
SALT_LENGTH = 16


def hash_password(password: str, pepper: str) -> tuple[bytes, bytes]:
    salt = secrets.token_bytes(SALT_LENGTH)                                             #Соучайная соль
    secret = password.encode("utf-8") + pepper.encode("utf-8")                          #Пароль с перцем
    digest = hash_secret_raw(
        secret=secret,
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=HASH_LENGTH,
        type=Type.ID,                                                                   #Argon2id
    )
    return digest, salt


def verify_password(password: str, pepper: str, salt: bytes, expected_hash: bytes) -> bool:
    secret = password.encode("utf-8") + pepper.encode("utf-8")
    actual_hash = hash_secret_raw(
        secret=secret,
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=HASH_LENGTH,
        type=Type.ID,
    )
    return hmac.compare_digest(actual_hash, expected_hash)
