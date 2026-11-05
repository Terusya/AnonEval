import asyncio
import hmac
import json
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import date
from typing import Literal

import pika
import redis.asyncio as redis
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field

from app.config import get_settings
from app.database import close_pool, get_pool, open_pool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("survey.api")
settings = get_settings()
redis_client: redis.Redis | None = None
publisher_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global redis_client, publisher_task
    open_pool()
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    publisher_task = asyncio.create_task(_outbox_publisher())
    yield
    publisher_task.cancel()
    try:
        await publisher_task
    except asyncio.CancelledError:
        pass
    await redis_client.aclose()
    close_pool()


app = FastAPI(title="Anonymous Survey Service", lifespan=lifespan)


class Identity(BaseModel):
    user_id: int
    role: Literal["student", "staff"]


class SurveyCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    subject_id: int = Field(gt=0)
    teacher_id: int = Field(gt=0)
    period_start: date
    period_end: date


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "closed"]


class ResponseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating_materials: int = Field(ge=2, le=5)
    rating_clarity: int = Field(ge=2, le=5)
    rating_engagement: int = Field(ge=2, le=5)


def identity(request: Request) -> Identity:                                                 #Проверяе знание секрета. Только nginx может сюда делать запросы
    provided_secret = request.headers.get("x-internal-secret", "")
    if not secrets.compare_digest(provided_secret, settings.app_internal_secret):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        user_id = int(request.headers.get("x-user-id", ""))
    except ValueError as error:
        raise HTTPException(status_code=401, detail="Unauthorized") from error
    role = request.headers.get("x-user-role")
    if user_id <= 0 or role not in {"student", "staff"}:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return Identity(user_id=user_id, role=role)


def require_staff(user: Identity) -> None:
    if user.role != "staff":
        raise HTTPException(status_code=403, detail="Insufficient role")


def _survey_projection(row: dict, own_mark: bool = False) -> dict[str, object]:
    return {
        "id": row["id"],
        "subject_id": row["subject_id"],
        "teacher_name": row["teacher_name"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "status": row["status"],
        "own_mark": own_mark,
    }


def _load_survey(connection, survey_id: int) -> dict:
    row = connection.execute(
        "SELECT s.id, s.subject_id, s.teacher_id, t.full_name AS teacher_name, "
        "s.period_start, s.period_end, s.status "
        "FROM surveys s JOIN teachers t ON t.id = s.teacher_id WHERE s.id = %s",
        (survey_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Survey not found")
    return row


def _student_enrolled(connection, user_id: int, subject_id: int) -> bool:
    return connection.execute(
        "SELECT 1 FROM enrollments WHERE user_id = %s AND subject_id = %s",
        (user_id, subject_id),
    ).fetchone() is not None


def _own_mark(connection, user_id: int, survey_id: int) -> bool:
    return connection.execute(
        "SELECT 1 FROM participation_marks WHERE user_id = %s AND survey_id = %s",
        (user_id, survey_id),
    ).fetchone() is not None


async def _increment_vote_attempt(user_id: int) -> int:                                     #rate-limit для голосования
    if redis_client is None:
        raise HTTPException(status_code=503, detail="Rate limiter unavailable")
    script = (
        "local value = redis.call('INCR', KEYS[1]); "
        "if value == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]); end; "
        "return value"
    )
    return int(await redis_client.eval(script, 1, f"vote-limit:{user_id}", 3600))


def _publish_outbox_batch() -> None:                                                        #Отправка в RabbitMQ
    with get_pool().connection() as connection:
        with connection.transaction():
            events = connection.execute(                                                    #Берем 20 неотправленных событий и блокируем их (FOR UPDATE SKIP LOCKED)
                "SELECT id, survey_id, event_type FROM survey_event_outbox "
                "WHERE published_at IS NULL ORDER BY id LIMIT 20 FOR UPDATE SKIP LOCKED"
            ).fetchall()
            if not events:
                return
            parameters = pika.URLParameters(settings.rabbitmq_url)                          #Подключаемся к RabbitMQ
            parameters.heartbeat = 30
            connection_to_broker = pika.BlockingConnection(parameters)
            try:
                channel = connection_to_broker.channel()
                channel.queue_declare(queue="summary_tasks", durable=True)                      #Создаем очередь, если её нет
                channel.confirm_delivery()
                for event in events:                                                            #Отправляем сообщение
                    channel.basic_publish(
                        exchange="",
                        routing_key="summary_tasks",
                        body=json.dumps(
                            {"event_id": event["id"], "survey_id": event["survey_id"], "type": event["event_type"]}
                        ),
                        properties=pika.BasicProperties(
                            delivery_mode=2,
                            content_type="application/json",
                            message_id=str(event["id"]),
                        ),
                    )
                    connection.execute(                                                             #Помечаем событие как отправленное
                        "UPDATE survey_event_outbox SET published_at = now() WHERE id = %s",
                        (event["id"],),
                    )
            finally:
                connection_to_broker.close()


async def _outbox_publisher() -> None:
    while True:
        try:
            await asyncio.to_thread(_publish_outbox_batch)
        except Exception:
            logger.exception("Could not publish survey outbox events")
        await asyncio.sleep(3)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:     #Защита от утечки информации внутренней структуры
    return JSONResponse(status_code=400, content={"detail": "Invalid request"})


@app.exception_handler(Exception)                                                               
async def unexpected_error_handler(_: Request, error: Exception) -> JSONResponse:
    logger.exception("Unexpected request failure", exc_info=error)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/surveys")                                                                        
def list_surveys(
    status: Literal["draft", "active", "closed"] | None = None,
    teacher_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
    user: Identity = Depends(identity),
) -> dict[str, object]:
    if limit < 1 or limit > 100 or offset < 0 or (teacher_id is not None and teacher_id < 1):
        raise HTTPException(status_code=400, detail="Invalid pagination or filter")

    clauses: list[str] = []
    values: list[object] = []
    if user.role == "student":
        clauses.extend(("s.status = 'active'", "e.user_id = %s"))
        values.append(user.user_id)
        if status not in (None, "active"):
            return {"items": [], "total": 0}
    elif status is not None:
        clauses.append("s.status = %s")
        values.append(status)

    if teacher_id is not None:
        clauses.append("s.teacher_id = %s")
        values.append(teacher_id)
    where_clause = " WHERE " + " AND ".join(clauses) if clauses else ""
    from_clause = "FROM surveys s JOIN teachers t ON t.id = s.teacher_id"
    if user.role == "student":
        from_clause += " JOIN enrollments e ON e.subject_id = s.subject_id"
    with get_pool().connection() as connection:
        total = connection.execute(
            f"SELECT count(*) AS total {from_clause}{where_clause}", tuple(values)
        ).fetchone()["total"]
        rows = connection.execute(                                                          
            "SELECT s.id, s.subject_id, s.teacher_id, t.full_name AS teacher_name, "
            "s.period_start, s.period_end, s.status "
            f"{from_clause}{where_clause} ORDER BY s.id LIMIT %s OFFSET %s",
            (*values, limit, offset),
        ).fetchall()
        items = [
            _survey_projection(row, _own_mark(connection, user.user_id, row["id"]))
            for row in rows
        ]
    return {"items": items, "total": total}


@app.get("/api/v1/surveys/{survey_id}")
def get_survey(survey_id: int, user: Identity = Depends(identity)) -> dict[str, object]:
    with get_pool().connection() as connection:
        survey = _load_survey(connection, survey_id)    
        if user.role == "student":
            if not _student_enrolled(connection, user.user_id, survey["subject_id"]):
                raise HTTPException(status_code=403, detail="Not enrolled in this subject")
            if survey["status"] != "active":
                raise HTTPException(status_code=404, detail="Survey not found")
            own_mark = _own_mark(connection, user.user_id, survey_id)
        else:
            own_mark = False
    return _survey_projection(survey, own_mark)


@app.post("/api/v1/surveys", status_code=201)                                                               #Создание опроса
def create_survey(payload: SurveyCreate, user: Identity = Depends(identity)) -> dict[str, object]:
    require_staff(user)
    if payload.period_end <= payload.period_start:
        raise HTTPException(status_code=400, detail="Invalid survey period")
    with get_pool().connection() as connection:
        subject = connection.execute(
            "SELECT 1 FROM subjects WHERE id = %s", (payload.subject_id,)
        ).fetchone()
        teacher = connection.execute(
            "SELECT full_name FROM teachers WHERE id = %s", (payload.teacher_id,)
        ).fetchone()
        if subject is None or teacher is None:
            raise HTTPException(status_code=404, detail="Subject or teacher not found")
        row = connection.execute(                                                                               #Статус берётся из бд, а не из запроса, также как и кем создано берётся не из запроса, а из user.user_id
            "INSERT INTO surveys "
            "(subject_id, teacher_id, period_start, period_end, created_by) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id, subject_id, teacher_id, "
            "period_start, period_end, status",
            (payload.subject_id, payload.teacher_id, payload.period_start, payload.period_end, user.user_id),
        ).fetchone()
    return {
        "id": row["id"],
        "subject_id": row["subject_id"],
        "teacher_id": row["teacher_id"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "status": row["status"],
    }


@app.patch("/api/v1/surveys/{survey_id}/status")
def update_status(
    survey_id: int, payload: StatusChange, user: Identity = Depends(identity)
) -> dict[str, object]:
    require_staff(user)
    with get_pool().connection() as connection:
        with connection.transaction():
            survey = connection.execute(                                                                #Блокируем строку
                "SELECT id, status, subject_id FROM surveys WHERE id = %s FOR UPDATE", (survey_id,)
            ).fetchone()
            if survey is None:
                raise HTTPException(status_code=404, detail="Survey not found")
            old_status = survey["status"]
            new_status = payload.status
            if old_status == new_status:                                                                #Если статус тот же - ничего не делаем (идемпотентность)
                return {"id": survey_id, "status": new_status}
            if (old_status, new_status) not in {("draft", "active"), ("active", "closed")}:             #Проверяем допустимость перехода
                raise HTTPException(status_code=400, detail="Invalid status transition")
            connection.execute(                                                                         #Обновляем
                "UPDATE surveys SET status = %s WHERE id = %s", (new_status, survey_id)
            )
            connection.execute(                                                                         #Пишем в аудит
                "INSERT INTO audit_log (actor_id, action, object_type, object_id, payload) "
                "VALUES (%s, 'survey_status_changed', 'survey', %s, %s)",
                (user.user_id, survey_id, Jsonb({"old_status": old_status, "new_status": new_status})),
            )
            if new_status == "active":                                                                  #Имитация почты
                students = connection.execute(                                                          #Ищем студентов
                    "SELECT user_id FROM enrollments WHERE subject_id = %s", (survey["subject_id"],)
                ).fetchall()
                student_ids = [row["user_id"] for row in students]                                      #Пишем в лог, что письма отправлены конкретным ID
                logger.info(f"Email stub: Survey #{survey_id} published. Notification sent to student_ids: {student_ids}")
            if new_status == "closed":                                                                  #Если закрываем - создаем событие в outbox
                connection.execute(
                    "INSERT INTO survey_event_outbox (survey_id, event_type) "
                    "VALUES (%s, 'summary_requested') ON CONFLICT DO NOTHING",
                    (survey_id,),
                )
    return {"id": survey_id, "status": payload.status}


@app.post("/api/v1/surveys/{survey_id}/responses", status_code=201)
async def submit_response(
    survey_id: int, payload: ResponseCreate, user: Identity = Depends(identity)
) -> dict[str, str]:
    if user.role != "student":
        raise HTTPException(status_code=403, detail="Student role required")
    attempts = await _increment_vote_attempt(user.user_id)
    if attempts > 10:
        raise HTTPException(status_code=429, detail="Too many attempts")

    with get_pool().connection() as connection:
        with connection.transaction():
            survey = _load_survey(connection, survey_id)
            if not _student_enrolled(connection, user.user_id, survey["subject_id"]):
                raise HTTPException(status_code=403, detail="Not enrolled in this subject")
            if survey["status"] != "active":
                raise HTTPException(status_code=410, detail="Survey is not active")
            mark = connection.execute(
                "INSERT INTO participation_marks (user_id, survey_id) VALUES (%s, %s) "
                "ON CONFLICT (user_id, survey_id) DO NOTHING RETURNING id",
                (user.user_id, survey_id),
            ).fetchone()
            if mark is None:
                raise HTTPException(status_code=409, detail="Already submitted")
            connection.execute(                                                                             #Вставляем оценки (без user_id)
                "INSERT INTO survey_responses "
                "(survey_id, rating_materials, rating_clarity, rating_engagement) "
                "VALUES (%s, %s, %s, %s)",
                (survey_id, payload.rating_materials, payload.rating_clarity, payload.rating_engagement),
            )
            connection.execute(                                                                             #Аудит (без user_id)
                "INSERT INTO audit_log (action, object_type, object_id, payload) "
                "VALUES ('response_accepted', 'survey', %s, %s)",
                (survey_id, Jsonb({"result": "accepted"})),
            )
    return {"status": "accepted", "message": "Your response has been recorded"}


@app.get("/api/v1/surveys/{survey_id}/results")                                                         #Выгрузка результатов
def get_results(survey_id: int, user: Identity = Depends(identity)) -> dict[str, object]:
    require_staff(user)
    with get_pool().connection() as connection:
        survey = connection.execute(
            "SELECT id, status FROM surveys WHERE id = %s", (survey_id,)
        ).fetchone()
        if survey is None:
            raise HTTPException(status_code=404, detail="Survey not found")
        if survey["status"] != "closed":
            raise HTTPException(status_code=409, detail="Survey is not closed")
        aggregate = connection.execute(                                                                     #Считаем агрегаты
            "SELECT count(*) AS responses_count, avg(rating_materials) AS avg_materials, "
            "avg(rating_clarity) AS avg_clarity, avg(rating_engagement) AS avg_engagement "
            "FROM survey_responses WHERE survey_id = %s",
            (survey_id,),
        ).fetchone()
        if aggregate["responses_count"] < 5:                                                                #Проверяем, что ответов >= 5 
            raise HTTPException(status_code=409, detail="At least five responses are required")
        distributions = connection.execute(
            "SELECT rating_materials, rating_clarity, rating_engagement, count(*) AS count "
            "FROM survey_responses WHERE survey_id = %s "
            "GROUP BY rating_materials, rating_clarity, rating_engagement",
            (survey_id,),
        ).fetchall()
        distribution = {str(rating): {"materials": 0, "clarity": 0, "engagement": 0} for rating in range(2, 6)}
        for row in distributions:
            for criterion in ("materials", "clarity", "engagement"):
                rating = row[f"rating_{criterion}"]
                distribution[str(rating)][criterion] += row["count"]
        connection.execute(
            "INSERT INTO audit_log (actor_id, action, object_type, object_id) "
            "VALUES (%s, 'results_exported', 'survey', %s)",
            (user.user_id, survey_id),
        )
    return {
        "survey_id": survey_id,
        "responses_count": aggregate["responses_count"],
        "avg_materials": round(float(aggregate["avg_materials"]), 2),
        "avg_clarity": round(float(aggregate["avg_clarity"]), 2),
        "avg_engagement": round(float(aggregate["avg_engagement"]), 2),
        "distribution": distribution,
    }


@app.post("/api/v1/surveys/{survey_id}/summaries")
def request_summary(survey_id: int, user: Identity = Depends(identity)) -> None:
    require_staff(user)
    with get_pool().connection() as connection:
        survey = connection.execute(
            "SELECT status FROM surveys WHERE id = %s", (survey_id,)
        ).fetchone()
        if survey is None:
            raise HTTPException(status_code=404, detail="Survey not found")
        if survey["status"] != "closed":
            raise HTTPException(status_code=409, detail="Survey is not closed")
        response_count = connection.execute(
            "SELECT count(*) AS total FROM survey_responses WHERE survey_id = %s",
            (survey_id,),
        ).fetchone()["total"]
        if response_count < 5:
            raise HTTPException(status_code=409, detail="At least five responses are required")
    raise HTTPException(status_code=501, detail="Summary generation is temporarily disabled")
