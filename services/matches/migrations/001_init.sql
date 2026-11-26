CREATE TABLE players (
    id INT IDENTITY(1,1) PRIMARY KEY,
    lc_user NVARCHAR(100) NOT NULL CONSTRAINT uq_players_lc_user UNIQUE
);

CREATE TABLE rooms (
    id INT IDENTITY(1,1) PRIMARY KEY,
    room_code NVARCHAR(16) NOT NULL CONSTRAINT uq_rooms_room_code UNIQUE,
    host_id INT NOT NULL REFERENCES players(id),
    current_status NVARCHAR(20) NOT NULL CONSTRAINT df_rooms_status DEFAULT 'Created'
        CONSTRAINT ck_rooms_status CHECK (current_status IN ('Created', 'Active', 'Inactive', 'Finished')),
    duration_min INT NOT NULL CONSTRAINT df_rooms_duration DEFAULT 30,
    creation_time NVARCHAR(40) NOT NULL,   -- UTC ISO strings, as written by common.to_db_time
    start_time NVARCHAR(40) NULL,
    end_time NVARCHAR(40) NULL,
    last_polled_at NVARCHAR(40) NULL,
    poll_error NVARCHAR(MAX) NULL
);

CREATE TABLE submissions (
    id INT IDENTITY(1,1) PRIMARY KEY,
    room_id INT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    player_id INT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    problem_id INT NOT NULL,               -- catalog's problems.id, no FK across the seam
    submitted_at NVARCHAR(40) NOT NULL,
    current_status NVARCHAR(20) NOT NULL
        CONSTRAINT ck_submissions_status CHECK (current_status IN ('Accepted', 'Wrong_Answer', 'Time_Limit', 'Pending'))
);

CREATE TABLE room_problems (
    id INT IDENTITY(1,1) PRIMARY KEY,
    room_id INT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    problem_id INT NOT NULL,               -- catalog's problems.id, no FK across the seam
    display_order INT NOT NULL,
    CONSTRAINT uq_room_problems_problem UNIQUE (room_id, problem_id),
    CONSTRAINT uq_room_problems_order UNIQUE (room_id, display_order)
);

CREATE TABLE room_players (
    id INT IDENTITY(1,1) PRIMARY KEY,
    room_id INT NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    player_id INT NOT NULL REFERENCES players(id) ON DELETE CASCADE,
    joined_at NVARCHAR(40) NOT NULL,
    score INT NOT NULL CONSTRAINT df_room_players_score DEFAULT 0,
    result NVARCHAR(20) NOT NULL CONSTRAINT df_room_players_result DEFAULT 'Created'
        CONSTRAINT ck_room_players_result CHECK (result IN ('Created', 'In_Progress', 'Winner', 'Loser')),
    CONSTRAINT uq_room_players UNIQUE (room_id, player_id)
);

CREATE TABLE health_check (id INT PRIMARY KEY, checked_at DATETIME2 NULL);
INSERT INTO health_check (id, checked_at) VALUES (1, NULL);