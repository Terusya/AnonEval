CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash BYTEA NOT NULL,
    password_salt BYTEA NOT NULL,
    role VARCHAR(32) NOT NULL CHECK (role IN ('student', 'staff')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_users_role ON users(role);

CREATE TABLE teachers (
    id BIGSERIAL PRIMARY KEY,
    full_name VARCHAR(200) NOT NULL UNIQUE
);

CREATE TABLE subjects (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL UNIQUE
);

CREATE TABLE enrollments (
    user_id BIGINT NOT NULL REFERENCES users(id),
    subject_id BIGINT NOT NULL REFERENCES subjects(id),
    enrolled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, subject_id)
);
CREATE INDEX idx_enrollments_subject ON enrollments(subject_id);

CREATE TABLE surveys (
    id BIGSERIAL PRIMARY KEY,
    subject_id BIGINT NOT NULL REFERENCES subjects(id),
    teacher_id BIGINT NOT NULL REFERENCES teachers(id),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'closed')),
    created_by BIGINT NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_survey_period CHECK (period_end > period_start)
);
CREATE INDEX idx_surveys_status ON surveys(status);
CREATE INDEX idx_surveys_subject ON surveys(subject_id);
CREATE INDEX idx_surveys_teacher ON surveys(teacher_id);
CREATE INDEX idx_surveys_created_by ON surveys(created_by);

CREATE TABLE survey_responses (
    id BIGSERIAL PRIMARY KEY,
    survey_id BIGINT NOT NULL REFERENCES surveys(id),
    rating_materials SMALLINT NOT NULL CHECK (rating_materials BETWEEN 2 AND 5),
    rating_clarity SMALLINT NOT NULL CHECK (rating_clarity BETWEEN 2 AND 5),
    rating_engagement SMALLINT NOT NULL CHECK (rating_engagement BETWEEN 2 AND 5),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_responses_survey ON survey_responses(survey_id);

CREATE TABLE participation_marks (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    survey_id BIGINT NOT NULL REFERENCES surveys(id),
    marked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_participation UNIQUE (user_id, survey_id)
);
CREATE INDEX idx_participation_survey ON participation_marks(survey_id);

CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    actor_id BIGINT REFERENCES users(id),
    action VARCHAR(64) NOT NULL,
    object_type VARCHAR(64) NOT NULL,
    object_id BIGINT,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    payload JSONB
);
CREATE INDEX idx_audit_ts ON audit_log(ts DESC);
CREATE INDEX idx_audit_actor ON audit_log(actor_id);

CREATE TABLE llm_summaries (
    id BIGSERIAL PRIMARY KEY,
    survey_id BIGINT NOT NULL REFERENCES surveys(id),
    teacher_id BIGINT NOT NULL REFERENCES teachers(id),
    summary_text TEXT NOT NULL,
    model_version VARCHAR(64) NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    requested_by BIGINT NOT NULL REFERENCES users(id),
    CONSTRAINT uq_summary_per_survey UNIQUE (survey_id)
);
CREATE INDEX idx_summaries_survey ON llm_summaries(survey_id);

CREATE TABLE password_reset_tokens (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    token_hash BYTEA NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_password_reset_user ON password_reset_tokens(user_id);

CREATE TABLE survey_event_outbox (
    id BIGSERIAL PRIMARY KEY,
    survey_id BIGINT NOT NULL REFERENCES surveys(id),
    event_type VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    CONSTRAINT uq_survey_event UNIQUE (survey_id, event_type)
);
CREATE INDEX idx_survey_event_outbox_pending ON survey_event_outbox(id) WHERE published_at IS NULL;
