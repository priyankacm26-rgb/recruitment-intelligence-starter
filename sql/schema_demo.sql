
USE recruitment_demo;

CREATE TABLE IF NOT EXISTS candidates (
  candidate_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  first_name VARCHAR(100) NOT NULL,
  last_name VARCHAR(100),
  email VARCHAR(254) NULL,
  phone VARCHAR(40),
  city VARCHAR(120),
  current_title VARCHAR(200),
  years_experience DECIMAL(5,2),
  skills JSON,
  resume_path VARCHAR(500),
  resume_text LONGTEXT,
  source VARCHAR(100),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_candidate_email(email),
  INDEX ix_candidate_city(city)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS jobs (
  job_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  title VARCHAR(250) NOT NULL,
  description TEXT,
  source VARCHAR(100),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS candidate_jobs (
  candidate_id BIGINT UNSIGNED NOT NULL,
  job_id BIGINT UNSIGNED NOT NULL,
  source VARCHAR(100),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(candidate_id, job_id),
  FOREIGN KEY(candidate_id) REFERENCES candidates(candidate_id),
  FOREIGN KEY(job_id) REFERENCES jobs(job_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS email_ingestion_logs (
  ingestion_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  provider VARCHAR(80) NOT NULL,
  provider_message_id VARCHAR(255) NOT NULL,
  sender VARCHAR(254),
  subject VARCHAR(500),
  attachment_name VARCHAR(350),
  status ENUM('received','processed','duplicate','skipped','failed','review')
    NOT NULL DEFAULT 'received',
  candidate_id BIGINT UNSIGNED NULL,
  error_message TEXT,
  received_at DATETIME,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_email_attachment(provider, provider_message_id, attachment_name),
  INDEX ix_ingestion_status(status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS chat_messages (
  message_id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
  session_id VARCHAR(100) NOT NULL,
  role ENUM('user','assistant') NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  INDEX ix_chat_session(session_id, message_id)
) ENGINE=InnoDB;
