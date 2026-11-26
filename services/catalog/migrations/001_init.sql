CREATE TABLE topics (
    id INT IDENTITY(1,1) PRIMARY KEY,
    topic_name NVARCHAR(100) NOT NULL CONSTRAINT uq_topics_topic_name UNIQUE
);

CREATE TABLE problems (
    id INT IDENTITY(1,1) PRIMARY KEY,
    title NVARCHAR(300) NOT NULL,
    lc_id NVARCHAR(200) NOT NULL CONSTRAINT uq_problems_lc_id UNIQUE,
    lc_url NVARCHAR(500) NOT NULL,
    difficulty NVARCHAR(10) NOT NULL
        CONSTRAINT ck_problems_difficulty CHECK (difficulty IN ('Easy', 'Medium', 'Hard'))
);

CREATE TABLE problem_topics (
    id INT IDENTITY(1,1) PRIMARY KEY,
    problem_id INT NOT NULL REFERENCES problems(id) ON DELETE CASCADE,
    topic_id INT NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    CONSTRAINT uq_problem_topics UNIQUE (problem_id, topic_id)
);

-- /health writes here to prove the service can write its own database.
CREATE TABLE health_check (id INT PRIMARY KEY, checked_at DATETIME2 NULL);
INSERT INTO health_check (id, checked_at) VALUES (1, NULL);