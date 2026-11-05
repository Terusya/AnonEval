import os

from app.config import get_settings
from app.database import close_pool, get_pool, open_pool
from app.security import hash_password


DEMO_USERS = (
    ("student1", "DEMO_STUDENT1_PASSWORD", "student"),
    ("student2", "DEMO_STUDENT2_PASSWORD", "student"),
    ("staff", "DEMO_STAFF_PASSWORD", "staff"),
)


def main() -> None:
    settings = get_settings()
    for _, variable, _ in DEMO_USERS:
        if not os.environ.get(variable):
            raise RuntimeError(f"{variable} must be set")

    open_pool()
    try:
        with get_pool().connection() as connection:
            with connection.transaction():
                ids: dict[str, int] = {}
                for username, variable, role in DEMO_USERS:
                    password_hash, password_salt = hash_password(
                        os.environ[variable], settings.pepper_secret
                    )
                    row = connection.execute(
                        "INSERT INTO users (username, password_hash, password_salt, role) "
                        "VALUES (%s, %s, %s, %s) "
                        "ON CONFLICT (username) DO UPDATE SET "
                        "password_hash = EXCLUDED.password_hash, "
                        "password_salt = EXCLUDED.password_salt, role = EXCLUDED.role "
                        "RETURNING id",
                        (username, password_hash, password_salt, role),
                    ).fetchone()
                    ids[username] = row["id"]

                subjects = []
                teachers = []
                for name in ("Основы безопасных систем", "Информационная безопасность"):
                    subjects.append(
                        connection.execute(
                            "INSERT INTO subjects (name) VALUES (%s) "
                            "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
                            (name,),
                        ).fetchone()["id"]
                    )
                for name in ("Иванов Иван Иванович", "Петрова Анна Сергеевна"):
                    teachers.append(
                        connection.execute(
                            "INSERT INTO teachers (full_name) VALUES (%s) "
                            "ON CONFLICT (full_name) DO UPDATE SET full_name = EXCLUDED.full_name RETURNING id",
                            (name,),
                        ).fetchone()["id"]
                    )

                for student, subject_id in (("student1", subjects[0]), ("student2", subjects[1])):
                    connection.execute(
                        "INSERT INTO enrollments (user_id, subject_id) VALUES (%s, %s) "
                        "ON CONFLICT DO NOTHING",
                        (ids[student], subject_id),
                    )

                surveys = (
                    (subjects[0], teachers[0], ids["staff"], "active"),
                    (subjects[1], teachers[1], ids["staff"], "active"),
                    (subjects[0], teachers[1], ids["staff"], "closed"),
                )
                for subject_id, teacher_id, owner_id, status in surveys:
                    connection.execute(
                        "INSERT INTO surveys "
                        "(subject_id, teacher_id, period_start, period_end, status, created_by) "
                        "SELECT %s, %s, CURRENT_DATE - 30, CURRENT_DATE + 30, %s, %s "
                        "WHERE NOT EXISTS (SELECT 1 FROM surveys WHERE subject_id = %s "
                        "AND teacher_id = %s AND created_by = %s)",
                        (subject_id, teacher_id, status, owner_id, subject_id, teacher_id, owner_id),
                    )

                closed_survey = connection.execute(
                    "SELECT s.id FROM surveys s WHERE s.status = 'closed' "
                    "AND s.created_by = %s ORDER BY s.id LIMIT 1",
                    (ids["staff"],),
                ).fetchone()
                if closed_survey is not None:
                    response_count = connection.execute(
                        "SELECT count(*) AS total FROM survey_responses WHERE survey_id = %s",
                        (closed_survey["id"],),
                    ).fetchone()["total"]
                    sample_ratings = ((5, 4, 4), (4, 4, 3), (4, 5, 4), (3, 4, 4), (5, 5, 5))
                    for materials, clarity, engagement in sample_ratings[response_count:5]:
                        connection.execute(
                            "INSERT INTO survey_responses "
                            "(survey_id, rating_materials, rating_clarity, rating_engagement) "
                            "VALUES (%s, %s, %s, %s)",
                            (closed_survey["id"], materials, clarity, engagement),
                        )
    finally:
        close_pool()


if __name__ == "__main__":
    main()
