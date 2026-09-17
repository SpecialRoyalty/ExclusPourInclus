-- Migration additive et non destructive pour ExclusPourInclus V2.
-- Aucun DROP TABLE / DROP COLUMN n'est exécuté au démarrage.

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
  telegram_id BIGINT PRIMARY KEY,
  username TEXT,
  first_name TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  flow_state TEXT,
  flow_data JSONB NOT NULL DEFAULT '{}'::jsonb,
  declared_total INT NOT NULL DEFAULT 0,
  attempts INT NOT NULL DEFAULT 0,
  banned BOOLEAN NOT NULL DEFAULT FALSE,
  joined_main_at TIMESTAMPTZ,
  first_media_at TIMESTAMPTZ,
  valid_media_count INT NOT NULL DEFAULT 0,
  progress_milestone INT NOT NULL DEFAULT 0,
  first_warning_sent BOOLEAN NOT NULL DEFAULT FALSE,
  quota_warning_sent BOOLEAN NOT NULL DEFAULT FALSE,
  last_link_warning_at TIMESTAMPTZ,
  appeal_available BOOLEAN NOT NULL DEFAULT FALSE,
  ad_source TEXT,
  abandonment_state TEXT,
  feedback_text TEXT,
  feedback_at TIMESTAMPTZ,
  left_access_lost_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS flow_state TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS flow_data JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE users ADD COLUMN IF NOT EXISTS declared_total INT NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS attempts INT NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS banned BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS joined_main_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS first_media_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS valid_media_count INT NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS progress_milestone INT NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS first_warning_sent BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS quota_warning_sent BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_link_warning_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS appeal_available BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS ad_source TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS abandonment_state TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS feedback_text TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS feedback_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS left_access_lost_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS groups (
  chat_id BIGINT PRIMARY KEY,
  title TEXT,
  type TEXT NOT NULL DEFAULT 'detected',
  active BOOLEAN NOT NULL DEFAULT TRUE,
  targeted BOOLEAN NOT NULL DEFAULT FALSE,
  last_ad_message_id BIGINT,
  last_ad_extra_message_id BIGINT,
  last_ad_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE groups ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE groups ADD COLUMN IF NOT EXISTS targeted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE groups ADD COLUMN IF NOT EXISTS last_ad_message_id BIGINT;
ALTER TABLE groups ADD COLUMN IF NOT EXISTS last_ad_extra_message_id BIGINT;
ALTER TABLE groups ADD COLUMN IF NOT EXISTS last_ad_at TIMESTAMPTZ;
ALTER TABLE groups ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE groups ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS applications (
  id BIGSERIAL PRIMARY KEY,
  telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'draft',
  gallery_file_id TEXT,
  gallery_unique_id TEXT,
  sample_file_id TEXT,
  sample_unique_id TEXT,
  sample_type TEXT,
  attempt_number INT NOT NULL DEFAULT 1,
  admin_decision_by BIGINT,
  rejection_reason TEXT,
  decision_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE applications ADD COLUMN IF NOT EXISTS gallery_file_id TEXT;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS gallery_unique_id TEXT;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS sample_file_id TEXT;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS sample_unique_id TEXT;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS sample_type TEXT;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS attempt_number INT NOT NULL DEFAULT 1;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS rejection_reason TEXT;
ALTER TABLE applications ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS payments (
  id BIGSERIAL PRIMARY KEY,
  telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE SET NULL,
  amount NUMERIC(10,2) NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',
  proof_file_id TEXT,
  proof_type TEXT,
  admin_decision_by BIGINT,
  rejection_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at TIMESTAMPTZ
);

ALTER TABLE payments ADD COLUMN IF NOT EXISTS admin_decision_by BIGINT;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS rejection_reason TEXT;

CREATE TABLE IF NOT EXISTS invite_links (
  id BIGSERIAL PRIMARY KEY,
  telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
  chat_id BIGINT NOT NULL,
  invite_link TEXT NOT NULL,
  expected_user_id BIGINT NOT NULL,
  used_by BIGINT,
  access_kind TEXT NOT NULL DEFAULT 'free',
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ,
  used_at TIMESTAMPTZ,
  revoked_at TIMESTAMPTZ
);

ALTER TABLE invite_links ADD COLUMN IF NOT EXISTS expected_user_id BIGINT;
ALTER TABLE invite_links ADD COLUMN IF NOT EXISTS used_by BIGINT;
ALTER TABLE invite_links ADD COLUMN IF NOT EXISTS access_kind TEXT NOT NULL DEFAULT 'free';
ALTER TABLE invite_links ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE invite_links ADD COLUMN IF NOT EXISTS used_at TIMESTAMPTZ;
ALTER TABLE invite_links ADD COLUMN IF NOT EXISTS revoked_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS media_hashes (
  id BIGSERIAL PRIMARY KEY,
  telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE SET NULL,
  chat_id BIGINT,
  message_id BIGINT,
  file_unique_id TEXT UNIQUE,
  media_type TEXT,
  counted BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS appeals (
  id BIGSERIAL PRIMARY KEY,
  telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
  failure_reason TEXT NOT NULL,
  appeal_text TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  admin_decision_by BIGINT,
  rejection_reason TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS new_link_requests (
  id BIGSERIAL PRIMARY KEY,
  telegram_id BIGINT NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  admin_decision_by BIGINT,
  processing_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  decided_at TIMESTAMPTZ
);

ALTER TABLE new_link_requests ADD COLUMN IF NOT EXISTS processing_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS admin_sessions (
  admin_id BIGINT PRIMARY KEY,
  state TEXT,
  data JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scheduled_deletions (
  id BIGSERIAL PRIMARY KEY,
  chat_id BIGINT NOT NULL,
  message_id BIGINT NOT NULL,
  delete_at TIMESTAMPTZ NOT NULL,
  attempts INT NOT NULL DEFAULT 0,
  UNIQUE(chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS analytics_events (
  id BIGSERIAL PRIMARY KEY,
  event TEXT NOT NULL,
  telegram_id BIGINT,
  source TEXT,
  data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS broadcasts (
  id BIGSERIAL PRIMARY KEY,
  admin_id BIGINT NOT NULL,
  category TEXT NOT NULL,
  source_chat_id BIGINT NOT NULL,
  source_message_id BIGINT NOT NULL,
  total_targets INT NOT NULL DEFAULT 0,
  sent_count INT NOT NULL DEFAULT 0,
  failed_count INT NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS pot_transactions (
  id BIGSERIAL PRIMARY KEY,
  amount NUMERIC(10,2) NOT NULL,
  reason TEXT NOT NULL,
  created_by BIGINT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS logs (
  id BIGSERIAL PRIMARY KEY,
  level TEXT NOT NULL DEFAULT 'info',
  event TEXT NOT NULL,
  telegram_id BIGINT,
  chat_id BIGINT,
  data JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_status_updated ON users(status, updated_at);
CREATE INDEX IF NOT EXISTS idx_users_banned ON users(banned) WHERE banned=TRUE;
CREATE INDEX IF NOT EXISTS idx_users_temp_joined ON users(joined_main_at) WHERE status='temporary_member';
CREATE INDEX IF NOT EXISTS idx_users_flow_updated ON users(updated_at) WHERE flow_state IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_applications_status_created ON applications(status, created_at);
CREATE INDEX IF NOT EXISTS idx_payments_status_created ON payments(status, created_at);
CREATE INDEX IF NOT EXISTS idx_invites_status_expiry ON invite_links(status, expires_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_invite_links_value ON invite_links(invite_link);
CREATE INDEX IF NOT EXISTS idx_appeals_status_created ON appeals(status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_new_link_requests_active_user
  ON new_link_requests(telegram_id) WHERE status IN ('pending','processing');
CREATE INDEX IF NOT EXISTS idx_events_name_created ON analytics_events(event, created_at);
CREATE INDEX IF NOT EXISTS idx_events_user_created ON analytics_events(telegram_id, created_at);
CREATE INDEX IF NOT EXISTS idx_deletions_due ON scheduled_deletions(delete_at);
CREATE INDEX IF NOT EXISTS idx_logs_created ON logs(created_at);

INSERT INTO settings(key,value) VALUES
  ('schema_version', '2'),
  ('ad_text', $txt$🔒 Communauté privée francophone

🎬 Accès gratuit réservé aux auteurs et producteurs de leurs propres contenus.

💎 Accès Premium disponible sans quota de contribution.

🛡 Chaque demande est vérifiée manuellement afin de protéger la communauté.$txt$),
  ('ad_media_file_id', ''),
  ('ad_media_type', ''),
  ('welcome_text', $txt$Bienvenue 👋

Ce bot gère l’accès à une communauté privée francophone.

L’accès gratuit est réservé aux auteurs et producteurs capables de partager leurs propres photos ou vidéos.

Un accès Premium sans quota de contribution est également disponible après vérification manuelle du paiement.

Souhaitez-vous continuer ?$txt$),
  ('welcome_media_file_id', ''),
  ('welcome_media_type', ''),
  ('gallery_example_file_id', ''),
  ('premium_price', '30 €'),
  ('paypal_link', ''),
  ('usdt_address', ''),
  ('max_declared_total', '100'),
  ('auto_pub_enabled', '0'),
  ('auto_pub_interval_minutes', '60'),
  ('auto_pub_next_at', ''),
  ('main_group', ''),
  ('scheduler_heartbeat', ''),
  ('last_auto_pub_at', ''),
  ('pot_balance', '0')
ON CONFLICT(key) DO NOTHING;
