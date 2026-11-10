"""Sessions, session videos, calibrations and session tracks.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE calibrations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            camera_id UUID NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
            image_points JSONB NOT NULL,
            pitch_points JSONB NOT NULL,
            pitch_length_m NUMERIC(5,1) NOT NULL,
            pitch_width_m NUMERIC(5,1) NOT NULL,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX calibrations_camera_idx ON calibrations (camera_id, created_at DESC)")
    op.execute("""
        CREATE TABLE sessions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            site_id UUID NOT NULL REFERENCES sites(id) ON DELETE CASCADE,
            source_id UUID NOT NULL REFERENCES cameras(id) ON DELETE RESTRICT,
            type VARCHAR(10) NOT NULL CONSTRAINT sessions_type_check CHECK (type IN ('training','match')),
            starts_at TIMESTAMPTZ NOT NULL,
            title VARCHAR(255),
            squad VARCHAR(100),
            status VARCHAR(12) NOT NULL DEFAULT 'uploading' CONSTRAINT sessions_status_check
                CHECK (status IN ('uploading','queued','processing','ready','failed')),
            progress SMALLINT NOT NULL DEFAULT 0 CONSTRAINT sessions_progress_check CHECK (progress BETWEEN 0 AND 100),
            stage VARCHAR(20),
            error TEXT,
            sync_offset_ms INTEGER NOT NULL DEFAULT 0,
            sprint_threshold_kmh NUMERIC(4,1) NOT NULL DEFAULT 19.0
                CONSTRAINT sessions_sprint_threshold_check CHECK (sprint_threshold_kmh BETWEEN 5 AND 40),
            calibration_id UUID REFERENCES calibrations(id) ON DELETE SET NULL,
            quality JSONB,
            summary_key TEXT,
            created_by UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX sessions_customer_starts_idx ON sessions (customer_id, starts_at DESC)")
    op.execute("""
        CREATE TABLE session_videos (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            position SMALLINT NOT NULL,
            original_filename VARCHAR(255),
            size_bytes BIGINT NOT NULL CONSTRAINT session_videos_size_check CHECK (size_bytes > 0),
            original_key TEXT NOT NULL,
            proxy_key TEXT,
            duration_ms INTEGER,
            fps NUMERIC(6,3),
            width INTEGER,
            height INTEGER,
            creation_time TIMESTAMPTZ,
            status VARCHAR(10) NOT NULL DEFAULT 'uploading' CONSTRAINT session_videos_status_check
                CHECK (status IN ('uploading','uploaded','failed','processed')),
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT session_videos_session_position_key UNIQUE (session_id, position)
                DEFERRABLE INITIALLY DEFERRED
        )
    """)
    op.execute("""
        CREATE TABLE session_tracks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            track_id INTEGER NOT NULL,
            cls VARCHAR(10) CONSTRAINT session_tracks_cls_check CHECK (cls IN ('person','ball')),
            team VARCHAR(5) CONSTRAINT session_tracks_team_check CHECK (team IN ('a','b','other')),
            team_corrected BOOLEAN NOT NULL DEFAULT false,
            on_pitch BOOLEAN,
            frames_count INTEGER NOT NULL,
            first_ms INTEGER NOT NULL,
            last_ms INTEGER NOT NULL,
            metrics JSONB,
            CONSTRAINT session_tracks_session_track_key UNIQUE (session_id, track_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE session_tracks")
    op.execute("DROP TABLE session_videos")
    op.execute("DROP TABLE sessions")
    op.execute("DROP TABLE calibrations")
