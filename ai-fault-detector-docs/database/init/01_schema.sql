-- VisionGuard AI — PostgreSQL 16 schema (initial migration)
--
-- Design notes
--  * Multi-tenant: every business table carries customer_id so queries can always be scoped
--    to one customer. Row-level security policies are added in a later migration once the
--    backend sets `app.customer_id` per request.
--  * Media (snapshots, clips, datasets, model files) live in object storage; the DB stores
--    storage keys only, never absolute paths or URLs.
--  * Camera credentials are stored encrypted by the backend (CREDENTIALS_ENCRYPTION_KEY);
--    the API never returns them.
--  * gen_random_uuid() is built into PostgreSQL 13+, so no extension is needed.

-- ---------------------------------------------------------------- tenancy
CREATE TABLE customers (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name              VARCHAR(255) NOT NULL,
    industry          VARCHAR(50) CHECK (industry IN ('restaurant','sports','retail','factory','school','security','other')),
    contact_email     VARCHAR(255),
    contact_phone     VARCHAR(50),
    subscription_plan VARCHAR(20) CHECK (subscription_plan IN ('pilot','starter','business','pro')),
    status            VARCHAR(20) NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','cancelled')),
    data_retention    JSONB NOT NULL DEFAULT '{"snapshots_days":14,"clips_days":14,"metadata_days":365}',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id   UUID REFERENCES customers(id) ON DELETE CASCADE,   -- NULL only for super_admin
    email         VARCHAR(255) NOT NULL,
    full_name     VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,                              -- argon2id
    role          VARCHAR(20) NOT NULL CHECK (role IN ('super_admin','customer_admin','operator','viewer')),
    telegram_chat_id VARCHAR(64),
    phone         VARCHAR(50),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT users_tenant_role CHECK ((role = 'super_admin') = (customer_id IS NULL))
);
CREATE UNIQUE INDEX uq_users_email ON users (lower(email));

CREATE TABLE refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(255) NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Machine access for integrations (POS, PLC gateways, Node-RED)
CREATE TABLE api_keys (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id  UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    name         VARCHAR(255) NOT NULL,
    key_prefix   VARCHAR(12) NOT NULL,
    key_hash     VARCHAR(255) NOT NULL UNIQUE,
    scopes       JSONB NOT NULL DEFAULT '[]',
    last_used_at TIMESTAMPTZ,
    revoked_at   TIMESTAMPTZ,
    created_by   UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE sites (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    name        VARCHAR(255) NOT NULL,
    location    TEXT,
    timezone    VARCHAR(64) NOT NULL DEFAULT 'Africa/Kigali',
    business_hours JSONB,          -- {"mon":[["08:00","22:00"]], ...}; used by rule schedules
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_sites_customer ON sites(customer_id);

-- ---------------------------------------------------------------- sources
CREATE TABLE cameras (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id        UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    site_id            UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    name               VARCHAR(255) NOT NULL,
    frigate_name       VARCHAR(64),          -- camera key in frigate/config.yml; NULL for non-Frigate sources
    source_type        VARCHAR(20) NOT NULL CHECK (source_type IN ('rtsp','usb','phone','screen','file')),
    source_url_encrypted BYTEA,              -- encrypted; never returned by the API
    resolution         VARCHAR(20),
    fps                SMALLINT NOT NULL DEFAULT 5 CHECK (fps BETWEEN 1 AND 30),
    ai_enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    status             VARCHAR(20) NOT NULL DEFAULT 'offline' CHECK (status IN ('online','offline','degraded','disabled')),
    last_seen_at       TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (site_id, name),
    UNIQUE (site_id, frigate_name)
);
CREATE INDEX idx_cameras_site ON cameras(site_id);

CREATE TABLE zones (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    camera_id   UUID NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    name        VARCHAR(255) NOT NULL,
    frigate_zone VARCHAR(64),               -- matching zone key in Frigate, if any
    zone_type   VARCHAR(30) CHECK (zone_type IN ('restricted','queue','kitchen','pitch','goal_area','counter','table','line','other')),
    -- Relative coordinates, 0..1: [[x,y],[x,y],...]. A 'line' zone has exactly 2 points.
    polygon     JSONB NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (camera_id, name)
);

-- ---------------------------------------------------------------- models
CREATE TABLE models (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id  UUID REFERENCES customers(id) ON DELETE CASCADE,   -- NULL = platform-wide base model
    name         VARCHAR(255) NOT NULL,
    version      VARCHAR(50) NOT NULL,
    architecture VARCHAR(50) NOT NULL,       -- e.g. rf-detr-n, ssdlite-mobilenet-v2, yolo11n
    license      VARCHAR(50) NOT NULL,       -- e.g. Apache-2.0, AGPL-3.0; checked before commercial activation
    base_model   VARCHAR(100),
    classes      JSONB NOT NULL,
    storage_key  TEXT NOT NULL,              -- models/{id}/weights.(pt|onnx|xml)
    metrics      JSONB,                      -- {"map50":..,"precision":..,"recall":..,"f1":..,"latency_ms":..}
    status       VARCHAR(20) NOT NULL DEFAULT 'training' CHECK (status IN ('training','testing','approved','archived','failed')),
    created_by   UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (customer_id, name, version)
);

-- "Active" is an assignment, not a model status: the same approved model can serve many cameras.
-- Exactly one active assignment per camera is enforced by the partial unique index.
CREATE TABLE model_assignments (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id   UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    model_id      UUID NOT NULL REFERENCES models(id) ON DELETE RESTRICT,
    camera_id     UUID NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    activated_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    activated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deactivated_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_one_active_model_per_camera ON model_assignments(camera_id) WHERE is_active;
-- Rollback = deactivate current row, reactivate the most recent previous row for that camera.

CREATE TABLE training_jobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id  UUID REFERENCES customers(id) ON DELETE CASCADE,
    model_id     UUID NOT NULL REFERENCES models(id) ON DELETE CASCADE,
    dataset_key  TEXT NOT NULL,
    params       JSONB NOT NULL DEFAULT '{"epochs":50,"image_size":640,"batch_size":16}',
    runner       VARCHAR(20) NOT NULL DEFAULT 'local' CHECK (runner IN ('local','colab','remote_gpu')),
    status       VARCHAR(20) NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','succeeded','failed','cancelled')),
    progress     NUMERIC(5,2) NOT NULL DEFAULT 0,
    current_epoch INTEGER,
    metrics_history JSONB NOT NULL DEFAULT '[]',   -- per-epoch loss/mAP for charts
    log_key      TEXT,
    error        TEXT,
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------- rules
CREATE TABLE fault_types (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID REFERENCES customers(id) ON DELETE CASCADE,   -- NULL = built-in template
    name        VARCHAR(255) NOT NULL,
    category    VARCHAR(30) CHECK (category IN ('security','safety','operations','sports','screen','equipment')),
    severity    VARCHAR(10) NOT NULL DEFAULT 'medium' CHECK (severity IN ('low','medium','high','critical')),
    description TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE rules (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id        UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    site_id            UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    camera_id          UUID REFERENCES cameras(id) ON DELETE CASCADE,   -- NULL = all cameras on the site
    zone_id            UUID REFERENCES zones(id) ON DELETE CASCADE,
    fault_type_id      UUID REFERENCES fault_types(id) ON DELETE SET NULL,
    name               VARCHAR(255) NOT NULL,
    -- presence:   object in zone
    -- count:      number of objects in zone compared to params.threshold ("more than 5 people")
    -- dwell:      one tracked object stays longer than duration (loitering)
    -- absence:    expected object missing / no motion (stopped conveyor, staff absent)
    -- line_cross: object crosses a 'line' zone in params.direction
    -- screen:     black / frozen / ocr_match / unauthorized_app (params.check)
    condition_type     VARCHAR(20) NOT NULL CHECK (condition_type IN ('presence','count','dwell','absence','line_cross','screen')),
    object_class       VARCHAR(100),
    params             JSONB NOT NULL DEFAULT '{}',  -- e.g. {"operator":">","threshold":5}
    min_confidence     NUMERIC(4,3) NOT NULL DEFAULT 0.600 CHECK (min_confidence BETWEEN 0 AND 1),
    duration_seconds   INTEGER NOT NULL DEFAULT 5 CHECK (duration_seconds >= 0),   -- how long the condition must hold
    cooldown_seconds   INTEGER NOT NULL DEFAULT 60 CHECK (cooldown_seconds >= 0),
    schedule           JSONB,          -- NULL = always; {"mode":"outside_business_hours"} or explicit windows
    severity           VARCHAR(10) NOT NULL DEFAULT 'medium' CHECK (severity IN ('low','medium','high','critical')),
    mode               VARCHAR(10) NOT NULL DEFAULT 'shadow' CHECK (mode IN ('shadow','live')),  -- shadow = record events, send no alerts
    action_config      JSONB NOT NULL DEFAULT '{}',
    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_by         UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_rules_camera ON rules(camera_id) WHERE is_active;
CREATE INDEX idx_rules_site ON rules(site_id) WHERE is_active;

-- ---------------------------------------------------------------- events
CREATE TABLE events (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id      UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    site_id          UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
    camera_id        UUID REFERENCES cameras(id) ON DELETE SET NULL,
    rule_id          UUID REFERENCES rules(id) ON DELETE SET NULL,
    zone_id          UUID REFERENCES zones(id) ON DELETE SET NULL,
    fault_type_id    UUID REFERENCES fault_types(id) ON DELETE SET NULL,
    model_id         UUID REFERENCES models(id) ON DELETE SET NULL,     -- which model produced it (feedback per model)
    frigate_event_id VARCHAR(64),
    rule_mode        VARCHAR(10) NOT NULL DEFAULT 'live' CHECK (rule_mode IN ('shadow','live')),
    started_at       TIMESTAMPTZ NOT NULL,     -- condition first true
    detected_at      TIMESTAMPTZ NOT NULL,     -- duration satisfied, event raised
    ended_at         TIMESTAMPTZ,
    confidence       NUMERIC(5,4),
    object_class     VARCHAR(100),
    object_count     INTEGER,
    track_id         VARCHAR(64),
    bbox             JSONB,                    -- relative [x1,y1,x2,y2]
    snapshot_key     TEXT,
    clip_key         TEXT,
    severity         VARCHAR(10) NOT NULL CHECK (severity IN ('low','medium','high','critical')),
    status           VARCHAR(20) NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved','false_positive')),
    acknowledged_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    acknowledged_at  TIMESTAMPTZ,
    resolved_by      UUID REFERENCES users(id) ON DELETE SET NULL,
    resolved_at      TIMESTAMPTZ,
    review_note      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (camera_id, frigate_event_id, rule_id)   -- idempotent ingestion of repeated MQTT messages
);
CREATE INDEX idx_events_customer_time ON events(customer_id, detected_at DESC);
CREATE INDEX idx_events_site_time ON events(site_id, detected_at DESC);
CREATE INDEX idx_events_camera_time ON events(camera_id, detected_at DESC);
CREATE INDEX idx_events_open ON events(customer_id, severity) WHERE status = 'open';

CREATE TABLE alert_deliveries (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id  UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    event_id     UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    channel      VARCHAR(20) NOT NULL CHECK (channel IN ('telegram','email','webhook','sms','dashboard')),
    recipient    VARCHAR(255),
    status       VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed','acknowledged')),
    attempts     SMALLINT NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ,
    response     TEXT,
    sent_at      TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_alert_deliveries_retry ON alert_deliveries(next_attempt_at) WHERE status = 'pending';

CREATE TABLE actions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id  UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    event_id     UUID REFERENCES events(id) ON DELETE SET NULL,     -- NULL for manual actions
    rule_id      UUID REFERENCES rules(id) ON DELETE SET NULL,
    action_type  VARCHAR(30) NOT NULL CHECK (action_type IN ('webhook','plc_stop','siren','camera_preset','mqtt_publish')),
    target       TEXT,
    payload      JSONB,
    requires_approval BOOLEAN NOT NULL DEFAULT TRUE,  -- see decision policy in 08-rules-and-actions.md
    approved_by  UUID REFERENCES users(id) ON DELETE SET NULL,
    status       VARCHAR(20) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','awaiting_approval','executed','failed','rejected')),
    triggered_by UUID REFERENCES users(id) ON DELETE SET NULL,      -- NULL = automatic
    executed_at  TIMESTAMPTZ,
    result       TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE feedback_labels (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    event_id    UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    label       VARCHAR(20) NOT NULL CHECK (label IN ('correct','false_positive','missed_fault','wrong_class')),
    corrected_class VARCHAR(100),
    note        TEXT,
    exported_to_dataset BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------- audit
-- Required by 11-security-privacy-policy.md: every login, export, manual action,
-- configuration change and model activation. Append-only; retained 12 months.
CREATE TABLE audit_logs (
    id          BIGSERIAL PRIMARY KEY,
    customer_id UUID REFERENCES customers(id) ON DELETE SET NULL,
    actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    actor_api_key_id UUID REFERENCES api_keys(id) ON DELETE SET NULL,
    action      VARCHAR(100) NOT NULL,      -- e.g. auth.login, event.review, clip.export, model.activate, rule.update
    entity_type VARCHAR(50),
    entity_id   UUID,
    details     JSONB,
    ip_address  INET,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_audit_customer_time ON audit_logs(customer_id, created_at DESC);

CREATE OR REPLACE FUNCTION audit_logs_block_changes() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_audit_logs_append_only
    BEFORE UPDATE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_block_changes();
-- DELETE is allowed only for the retention job (runs as table owner after 12 months).
