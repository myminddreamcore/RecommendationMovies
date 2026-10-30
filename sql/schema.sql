

CREATE TABLE IF NOT EXISTS users (
    id             SERIAL PRIMARY KEY,
    username       VARCHAR(100) NOT NULL,
    favorite_genre VARCHAR(60),
    created_at     DATE DEFAULT CURRENT_DATE
);

CREATE TABLE IF NOT EXISTS movies (
    id               INTEGER PRIMARY KEY,
    title_ru         TEXT NOT NULL,
    title_orig       TEXT,
    title_translated BOOLEAN,
    year             SMALLINT,
    genres_ru        TEXT,
    tags_ru          TEXT,
    country_ru       TEXT,
    language_ru      TEXT,
    director_ru      TEXT,
    rating_source    NUMERIC(4,2),
    n_raters_source  INTEGER,
    douban_id        BIGINT,
    imdb             TEXT
);

CREATE TABLE IF NOT EXISTS ratings (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
    movie_id    INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    rating      SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment     TEXT,
    review_date DATE DEFAULT CURRENT_DATE,
    useful_num  INTEGER DEFAULT 0,
    source      VARCHAR(10) DEFAULT 'import',
    CONSTRAINT uq_rating_user_movie UNIQUE (user_id, movie_id)
);
CREATE INDEX IF NOT EXISTS ix_ratings_movie ON ratings(movie_id);

