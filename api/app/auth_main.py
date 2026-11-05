import hashlib
import logging
import secrets
from hashlib import sha256
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.database import close_pool, get_pool, open_pool
from app.security import hash_password, verify_password

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("survey.auth")
settings = get_settings()
redis_client: redis.Redis | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):                                                             #Определяет работу сервера
    global redis_client
    open_pool()
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    yield                                                                                   #Работа сервера
    await redis_client.aclose()
    close_pool()


app = FastAPI(title="Anonymous Survey Auth Service", lifespan=lifespan)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")                                                   # Запрещены лишние поля
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64)


class ResetConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=128)
    new_password: str = Field(min_length=12, max_length=256)


def _get_redis() -> redis.Redis:                                                                #Проверка redis
    if redis_client is None:
        raise HTTPException(status_code=503, detail="Authentication service unavailable")
    return redis_client


def _internal_ok(request: Request) -> bool:
    supplied = request.headers.get("x-internal-secret", "")
    return secrets.compare_digest(supplied, settings.app_internal_secret)                       #Проверка секрета ПОЛНОСТЬЮ, чтобы не вычислили по времени сравнения


async def _check_rate_limit(key: str, limit: int, ttl: int) -> None:                            #Защита от брутфорса
    script = (
        "local value = redis.call('INCR', KEYS[1]); "                                           #Lua для redis, чтобы при одновременных get и set они выполнились последовательно, а не мешали друг другу
        "if value == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]); end; "
        "return value"
    )
    count = int(await _get_redis().eval(script, 1, key, ttl))
    if count > limit:
        raise HTTPException(status_code=429, detail="Too many requests")


@app.get("/health")                                                                             #200 если сервис жив
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/auth/login")                                                                                     
async def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, object]:              
    client_ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")      #IP клиента для rate-limit
    await _check_rate_limit(f"login-limit:{sha256(client_ip.encode()).hexdigest()}", 10, 60)                    #Не больше 10 попыток в минуту
    with get_pool().connection() as connection:                                                                 #Ищем пользователя в БД
        user = connection.execute(
            "SELECT id, username, role, password_hash, password_salt "
            "FROM users WHERE username = %s",                                                                   #Параметризованный запрос
            (payload.username,),
        ).fetchone()

    if user is None or not verify_password(                                                                     #Проверяем пароль
        payload.password, settings.pepper_secret, bytes(user["password_salt"]), bytes(user["password_hash"])
    ):
        raise HTTPException(status_code=401, detail="Invalid username or password")                             #Защита: "нет пользователя" и "неверный пароль" дают одинаковый ответ (от перебора логинов)
    session_id = secrets.token_urlsafe(32)                                                                      #Создаем сессию
    session_data = f"{user['id']}:{user['role']}:{user['username']}"
    await _get_redis().setex(f"session:{session_id}", settings.session_ttl_seconds, session_data)
    await _get_redis().sadd(f"sessions:user:{user['id']}", session_id)                                          #Сохраняем сессию в список сессий пользователя (для принудительного logout)
    await _get_redis().expire(f"sessions:user:{user['id']}", settings.session_ttl_seconds)
    response.set_cookie(                                                                                        #Отдаем Cookie
        key="survey_session",
        value=session_id,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return {"user_id": user["id"], "username": user["username"], "role": user["role"]}


@app.post("/api/v1/auth/logout", status_code=204)
async def logout(request: Request, response: Response) -> Response:
    session_id = request.cookies.get("survey_session")
    if session_id:                                                                              #Достаем user_id из сессии, чтобы удалить её из списка пользователя
        session_data = await _get_redis().get(f"session:{session_id}")
        if session_data:
            user_id = session_data.split(":", 1)[0]
            await _get_redis().srem(f"sessions:user:{user_id}", session_id)
        await _get_redis().delete(f"session:{session_id}")                                      #Удаляем саму сессию
    response.delete_cookie("survey_session", path="/")                                          #Удаляем Cookie у клиента
    response.status_code = 204
    return response


@app.get("/api/v1/auth/me")                                                                 #Проверка кто пользователь с помозью nginx
def me(request: Request) -> dict[str, object]:
    if not _internal_ok(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    user_id = request.headers.get("x-user-id")
    role = request.headers.get("x-user-role")
    username = request.headers.get("x-username")
    if not user_id or role not in {"student", "staff"} or not username:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"user_id": int(user_id), "username": username, "role": role}


@app.post("/api/v1/auth/password-reset/request")                                                                #Сброс пароля
async def request_password_reset(payload: ResetRequest, request: Request) -> dict[str, str]:
    client_ip = request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")
    await _check_rate_limit(f"reset-limit:{sha256(client_ip.encode()).hexdigest()}", 5, 60)
    with get_pool().connection() as connection:
        user = connection.execute(
            "SELECT id, username FROM users WHERE username = %s", (payload.username,)
        ).fetchone()
        if user is not None:                                                                                    #ТОЛЬКО если пользователь существует
            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode("utf-8")).digest()
            expires = datetime.now(timezone.utc) + timedelta(seconds=settings.reset_ttl_seconds)
            connection.execute(
                "INSERT INTO password_reset_tokens (user_id, token_hash, expires_at) "
                "VALUES (%s, %s, %s)",
                (user["id"], token_hash, expires),
            )
            logger.info("Local password reset message for %s: %s", user["username"], token)
    return {"message": "If the account exists, reset instructions have been sent"}                              #Возврат одинакового ответа, даже если пользователя нет, чтобы не составили список пользователей


@app.post("/api/v1/auth/password-reset/confirm")                                                        #Подтверждение сброса пароля
async def confirm_password_reset(payload: ResetConfirm) -> dict[str, str]:
    token_hash = hashlib.sha256(payload.token.encode("utf-8")).digest()
    with get_pool().connection() as connection:
        with connection.transaction():                                                                  #Транзакция: либо всё, либо ничего
            reset = connection.execute(
                "SELECT id, user_id FROM password_reset_tokens "
                "WHERE token_hash = %s AND consumed_at IS NULL AND expires_at > now() "
                "FOR UPDATE",
                (token_hash,),
            ).fetchone()
            if reset is None:
                raise HTTPException(status_code=400, detail="Invalid or expired reset token")
            password_hash, password_salt = hash_password(payload.new_password, settings.pepper_secret)  #Меняем пароль
            connection.execute(
                "UPDATE users SET password_hash = %s, password_salt = %s WHERE id = %s",
                (password_hash, password_salt, reset["user_id"]),
            )
            connection.execute(                                                                         #Помечаем токен как использованный
                "UPDATE password_reset_tokens SET consumed_at = now() WHERE id = %s",
                (reset["id"],),
            )
    redis_client = _get_redis()                                                                             #Отзываем ВСЕ сессии пользователя
    session_key = f"sessions:user:{reset['user_id']}"
    session_ids = await redis_client.smembers(session_key)
    if session_ids:
        await redis_client.delete(*(f"session:{session_id}" for session_id in session_ids))
    await redis_client.delete(session_key)
    return {"message": "Password updated"}


@app.get("/internal/verify")
async def verify_session(request: Request) -> Response:
    if not _internal_ok(request):                                                       #Проверяем, что запрос от Nginx
        return Response(status_code=401)
    session_id = request.cookies.get("survey_session")
    if not session_id:
        return Response(status_code=401)
    session_data = await _get_redis().get(f"session:{session_id}")
    if not session_data:
        return Response(status_code=401)
    user_id, role, username = session_data.split(":", 2)
    return Response(
        status_code=204,
        headers={"X-User-ID": user_id, "X-User-Role": role, "X-Username": username},
    )
