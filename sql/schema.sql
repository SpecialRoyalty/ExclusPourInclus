CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
  telegram_id BIGINT PRIMARY KEY,
  username TEXT,
  first_name TEXT,
  language TEXT,
  status TEXT DEFAULT 'new',
  profile_type TEXT,
  declared_total INT DEFAULT 0,
  declared_photos INT DEFAULT 0,
  declared_videos INT DEFAULT 0,
  attempts INT DEFAULT 0,
  joined_main_at TIMESTAMPTZ,
  first_media_at TIMESTAMPTZ,
  valid_media_count INT DEFAULT 0,
  banned BOOLEAN DEFAULT FALSE,
  flow_message_id BIGINT,
  flow_chat_id BIGINT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS groups (
  chat_id BIGINT PRIMARY KEY,
  title TEXT,
  type TEXT NOT NULL CHECK(type IN ('publicity','main')),
  active BOOLEAN DEFAULT TRUE,
  targeted BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS applications (
  id BIGSERIAL PRIMARY KEY,
  telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
  status TEXT DEFAULT 'draft',
  proof_file_id TEXT,
  proof_type TEXT DEFAULT 'photo',
  admin_decision_by BIGINT,
  decision_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS invite_links (
  id BIGSERIAL PRIMARY KEY,
  telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
  chat_id BIGINT NOT NULL,
  invite_link TEXT NOT NULL,
  expected_user_id BIGINT,
  used_by BIGINT,
  status TEXT DEFAULT 'active',
  created_at TIMESTAMPTZ DEFAULT now(),
  expires_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS media_hashes (
  id BIGSERIAL PRIMARY KEY,
  telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE SET NULL,
  chat_id BIGINT,
  message_id BIGINT,
  file_unique_id TEXT,
  perceptual_hash TEXT,
  media_type TEXT,
  counted BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(file_unique_id)
);

CREATE TABLE IF NOT EXISTS logs (
  id BIGSERIAL PRIMARY KEY,
  level TEXT DEFAULT 'info',
  event TEXT NOT NULL,
  telegram_id BIGINT,
  chat_id BIGINT,
  data JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS proposals (
  id BIGSERIAL PRIMARY KEY,
  proposer_id BIGINT REFERENCES users(telegram_id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  platform_link TEXT NOT NULL,
  status TEXT DEFAULT 'pending_admin',
  message_id BIGINT,
  yes_count INT DEFAULT 0,
  no_count INT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(),
  closed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS proposal_votes (
  proposal_id BIGINT REFERENCES proposals(id) ON DELETE CASCADE,
  voter_id BIGINT REFERENCES users(telegram_id) ON DELETE CASCADE,
  vote TEXT NOT NULL CHECK(vote IN ('yes','no')),
  created_at TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY(proposal_id, voter_id)
);

CREATE TABLE IF NOT EXISTS payments (
  id BIGSERIAL PRIMARY KEY,
  telegram_id BIGINT REFERENCES users(telegram_id) ON DELETE SET NULL,
  amount NUMERIC(10,2) NOT NULL,
  status TEXT DEFAULT 'pending',
  proof_file_id TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  decided_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS pot_transactions (
  id BIGSERIAL PRIMARY KEY,
  amount NUMERIC(10,2) NOT NULL,
  reason TEXT NOT NULL,
  created_by BIGINT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- upgrades safe
ALTER TABLE users ADD COLUMN IF NOT EXISTS flow_message_id BIGINT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS flow_chat_id BIGINT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS valid_media_count INT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS first_media_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS joined_main_at TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS attempts INT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS banned BOOLEAN DEFAULT FALSE;
ALTER TABLE groups ADD COLUMN IF NOT EXISTS targeted BOOLEAN DEFAULT TRUE;
ALTER TABLE groups ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now();
ALTER TABLE applications ADD COLUMN IF NOT EXISTS proof_type TEXT DEFAULT 'photo';

INSERT INTO settings(key,value) VALUES
('ad_text', '🔒 Communauté privée francophone\n\n• Accès sélectif\n• Contribution obligatoire\n• Vérification manuelle\n\nLes candidatures sont limitées.'),
('auto_pub_enabled', '0'),
('auto_pub_interval_minutes', '10'),
('pot_balance', '0')
ON CONFLICT(key) DO NOTHING;
