import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import \
    normalize
# колонки, которые мы всегда возвращаем клиенту в ответах API
SHOW_COLS = ["movie_id", "title_ru", "year", "genres_ru", "country_ru", "avg_rating", "n_ratings"]


def _py(v):
    if v is None or v is pd.NA: return None
    if isinstance(v, np.generic): v = v.item()  # напр. int64 -> int
    if isinstance(v, float) and v != v: return None
    return v


def _clean(df: pd.DataFrame) -> list:
    # orient="records" делает список вида [{col1: val1, ...}, {col1: val2...}]
    out = [{k: _py(v) for k, v in rec.items()} for rec in df.to_dict(orient="records")]
    for rec in out:
        if rec.get("year") is not None: rec["year"] = int(rec["year"])
    return out


class RecommenderEngine:
    def __init__(self, movies: pd.DataFrame, ratings: pd.DataFrame,
                 min_item_ratings: int = 20, min_content_ratings: int = 5,
                 pop_quantile: float = 0.90):
        self.min_item_ratings = min_item_ratings
        self.min_content_ratings = min_content_ratings
        self.pop_quantile = pop_quantile
        self.build(movies, ratings)

    def build(self, movies: pd.DataFrame, ratings: pd.DataFrame):
        ratings = ratings[["user_id", "movie_id", "rating"]].dropna().copy()
        ratings["user_id"] = ratings["user_id"].astype(int)
        ratings["movie_id"] = ratings["movie_id"].astype(int)
        ratings["rating"] = ratings["rating"].astype(float)

        # если один пользователь оценил фильм несколько раз, берем самую последнюю оценку
        ratings = ratings.drop_duplicates(["user_id", "movie_id"], keep="last")

        self.movies = movies.drop_duplicates("movie_id").set_index("movie_id", drop=False)

        g = ratings.groupby("movie_id")["rating"].agg(avg_rating="mean", n_ratings="count")
        v, R = g["n_ratings"], g["avg_rating"]
        self.m_threshold = float(v.quantile(self.pop_quantile))
        self.c_mean = float(R.mean())
        g["w_score"] = (v * R + self.m_threshold * self.c_mean) / (v + self.m_threshold)
        self.pop = g.sort_values("w_score", ascending=False)
        self.movies = self.movies.drop(
            columns=[c for c in ("avg_rating", "n_ratings") if c in self.movies.columns]).join(
            g[["avg_rating", "n_ratings"]])
        self.movies["n_ratings"] = self.movies["n_ratings"].fillna(0).astype(int)
        self.movies["avg_rating"] = self.movies["avg_rating"].round(2)


        #  User-Item
        self.user_ids = np.sort(ratings["user_id"].unique())
        self.movie_ids = np.sort(ratings["movie_id"].unique())
        # создаем словари для быстрого поиска индекса по ID пользователя или фильма
        self.u_idx = {u: i for i, u in enumerate(self.user_ids)}
        self.m_idx = {m: j for j, m in enumerate(self.movie_ids)}
        # преобразуем ID в индексы строк и столбцов для матрицы
        rows = ratings["user_id"].map(self.u_idx).to_numpy()
        cols = ratings["movie_id"].map(self.m_idx).to_numpy()
        # создаем разреженную матрицу оценок (строки=юзеры, столбцы=фильмы)
        self.R = csr_matrix((ratings["rating"].to_numpy(np.float32), (rows, cols)),
                            shape=(len(self.user_ids), len(self.movie_ids)))
        # нормализуем строки (пользователей) для косинусного сходства
        self.Rn_users = normalize(self.R, norm="l2", axis=1)
        # считаем сколько оценок получил каждый фильм (сумма ненулевых элементов в столбце)
        self.movie_counts = np.asarray((self.R > 0).sum(axis=0)).ravel()
        # получаем средний рейтинг каждого фильма в порядке movie_ids
        self.movie_avg = self.movies["avg_rating"].reindex(self.movie_ids).to_numpy(dtype=float)


        # Item-Based
        keep = np.where(self.movie_counts >= self.min_item_ratings)[0]
        self.item_cols = keep
        #  movie_id -> позиция
        self.item_pos = {self.movie_ids[j]: p for p, j in enumerate(keep)}
        Ri = self.R[:, keep].tocsr()
        user_mean = np.asarray(self.R.sum(axis=1)).ravel() / np.maximum(np.asarray((self.R > 0).sum(axis=1)).ravel(), 1)
        Rc = Ri.copy().tocoo()
        Rc.data = Rc.data - user_mean[Rc.row].astype(np.float32)  # вычитаем среднее из каждой оценки
        self.Item_cos = normalize(Ri.T.tocsr(), norm="l2", axis=1)
        self.Item_pear = normalize(Rc.tocsr().T.tocsr(), norm="l2", axis=1)


        # Content-Based
        self.c_ids = self.movies.index.to_numpy()
        self.c_pos = {m: i for i, m in enumerate(self.c_ids)}
        docs = [self._doc(r) for r in self.movies.itertuples()]
        # TF-IDF векторизатор: превращает списки токенов в матрицу весов
        # analyzer=lambda d: d означает, что мы сами подаем готовые списки токенов, а не строки
        self.tfidf = TfidfVectorizer(analyzer=lambda d: d, sublinear_tf=True, min_df=2)
        self.X = self.tfidf.fit_transform(docs).tocsr()
        self.c_counts = self.movies["n_ratings"].to_numpy()

    @staticmethod
    def _split(s):
        return [x.strip() for x in str(s).split(",") if x.strip() and x.strip() != "Не указан" and x.strip() != "nan"]

    def _doc(self, r):
        toks = []
        for gname in self._split(r.genres_ru): toks += [f"жанр:{gname}"] * 3
        for t in self._split(r.tags_ru): toks.append(f"тег:{t}")
        for c in self._split(r.country_ru): toks.append(f"страна:{c}")
        for l in self._split(r.language_ru): toks.append(f"язык:{l}")
        try:
            if pd.notna(r.year): toks.append(f"декада:{int(r.year) // 10 * 10}")
        except (TypeError, ValueError):
            pass
        return toks

    def _fmt(self, ids, scores, score_name="score"):
        df = self.movies.loc[list(ids), SHOW_COLS].copy()
        df[score_name] = np.round(np.asarray(scores, dtype=float), 4)
        return df.reset_index(drop=True)

    def exists(self, movie_id: int) -> bool:
        return int(movie_id) in self.movies.index

    def get_movie(self, movie_id: int):
        if not self.exists(movie_id): return None
        row = self.movies.loc[[int(movie_id)]]
        return _clean(row[SHOW_COLS + ["title_orig", "tags_ru", "language_ru", "director_ru"]])[0]

    def search(self, query: str, limit: int = 20):
        q = query.strip().lower()
        if not q: return []
        m = self.movies
        mask = m["title_ru"].astype(str).str.lower().str.contains(q, regex=False) | m["title_orig"].astype(
            str).str.lower().str.contains(q, regex=False)
        res = m[mask].sort_values("n_ratings", ascending=False).head(limit)
        return _clean(res[SHOW_COLS])

    def genres(self):
        s = self.movies["genres_ru"].dropna().str.split(", ").explode()
        return sorted(g for g in s.unique() if g and g != "Не указан")

    def popular(self, limit: int = 10, genre: str = None, min_year: int = None):
        ids = self.pop.index
        df = self.pop.join(self.movies[["title_ru", "year", "genres_ru", "country_ru"]], how="left").reset_index()
        df = df.rename(columns={"index": "movie_id"})
        if genre: df = df[df["genres_ru"].astype(str).str.contains(genre, regex=False)]
        if min_year: df = df[df["year"].fillna(0) >= min_year]
        df = df.head(limit).copy()
        df["avg_rating"] = df["avg_rating"].round(2)
        df["score"] = df["w_score"].round(4)
        return _clean(
            df[["movie_id", "title_ru", "year", "genres_ru", "country_ru", "avg_rating", "n_ratings", "score"]])

    def item_based(self, movie_id: int, limit: int = 10, method: str = "cosine"):
        movie_id = int(movie_id)
        M = self.Item_pear if method == "pearson" else self.Item_cos

        if movie_id in self.item_pos:
            vec = M[self.item_pos[movie_id]]
        elif movie_id in self.m_idx:
            col = self.R[:, self.m_idx[movie_id]].T
            vec = normalize(col, norm="l2", axis=1)
        else:
            return []

        # умножаем матрицу сходств на вектор фильма -> получаем сходство со всеми остальными
        sims = (M @ vec.T).toarray().ravel()

        # исключаем сам фильм из результатов
        if movie_id in self.item_pos: sims[self.item_pos[movie_id]] = -1

        top = np.argsort(-sims)[:limit]  # сортируем по убыванию и берем топ-N
        ids = [self.movie_ids[self.item_cols[p]] for p in top]  # восстанавливаем реальные ID фильмов
        return _clean(self._fmt(ids, sims[top], "score"))

    def user_vector(self, ratings: dict):
        vec = np.zeros(len(self.movie_ids), dtype=np.float32)
        for mid, r in ratings.items():
            j = self.m_idx.get(int(mid))
            if j is not None: vec[j] = r
        return vec

    def _neighbors(self, ratings: dict, exclude_user: int = None, k: int = 50):

        vec = self.user_vector(ratings)
        nrm = np.linalg.norm(vec)
        if nrm == 0: return np.array([], dtype=int), np.array([])
        # косинусное сходство текущего пользователя со всеми другими
        sims = np.asarray(self.Rn_users @ (vec / nrm)).ravel()
        # исключаем самого пользователя из поиска соседей
        if exclude_user is not None and int(exclude_user) in self.u_idx:
            sims[self.u_idx[int(exclude_user)]] = -1

        nb = np.argpartition(-sims, min(k, len(sims) - 1))[:k]
        nb = nb[sims[nb] > 0]  # оставляем только тех, у кого сходство > 0
        nb = nb[np.argsort(-sims[nb])]  # сортируем оставшихся по убыванию сходства
        return nb, sims[nb]

    def _cf_scores(self, ratings: dict, exclude_user: int = None, k: int = 50, min_support: int = 3):
        n = len(self.movie_ids)
        nb, S = self._neighbors(ratings, exclude_user, k)  # соседи и их веса (сходство)
        if len(nb) == 0: return np.full(n, np.nan), np.zeros(n), np.zeros(n)

        Rn = self.R[nb]
        # числитель: сумма (оценка соседа * сходство соседа) для каждого фильма
        num = np.asarray(Rn.T @ S).ravel()
        # знаменатель: сумма сходств тех соседей, кто оценил этот фильм
        den = np.asarray((Rn > 0).astype(np.float32).T @ S).ravel()
        # сколько соседей вообще оценили этот фильм
        cnt = np.asarray((Rn > 0).sum(axis=0)).ravel()

        lam = 1.0  # коэффициент сглаживания
        # если средний рейтинг фильма неизвестен, берем общий средний
        prior = np.where(np.isnan(self.movie_avg), self.c_mean, self.movie_avg)

        # формула предсказания: взвешенное среднее + сглаживание к среднему рейтингу фильма
        # условие: фильм оценили минимум min_support соседей и есть хоть какая-то сумма весов
        pred = np.where((cnt >= min_support) & (den > 0), (num + lam * prior) / (den + lam), np.nan)
        return pred, cnt, num  # pred - прогноз, cnt - поддержка, num - "сила" рекомендации

    def user_based(self, user_id: int, limit: int = 10, ratings: dict = None, k: int = 50):
        if ratings is None: ratings = self.ratings_of(user_id)
        if not ratings: return []

        pred, cnt, strength = self._cf_scores(ratings, exclude_user=user_id, k=k)

        # если предсказание не удалось (NaN), ставим силу -1 (исключить)
        strength = np.where(np.isnan(pred), -1.0, strength)

        # исключаем фильмы, которые пользователь уже оценил
        for mid in ratings:
            j = self.m_idx.get(int(mid))
            if j is not None: strength[j] = -1.0

        # исключаем непопулярные фильмы (мало оценок в базе)
        strength[self.movie_counts < self.min_content_ratings] = -1.0

        # сортируем по силе рекомендации (strength) и берем топ-N
        order = [j for j in np.argsort(-strength)[:limit] if strength[j] > 0]
        return _clean(self._fmt([self.movie_ids[j] for j in order], pred[order], "score"))

    def ratings_of(self, user_id: int) -> dict:
        if int(user_id) not in self.u_idx: return {}
        row = self.R[self.u_idx[int(user_id)]]
        return {int(self.movie_ids[j]): float(v) for j, v in zip(row.indices, row.data)}

    def content_based(self, movie_id: int, limit: int = 10):
        movie_id = int(movie_id)
        if movie_id not in self.c_pos: return []
        i = self.c_pos[movie_id]

        # косинусное сходство вектора фильма со всеми остальными векторами в TF-IDF матрице
        sims = (self.X @ self.X[i].T).toarray().ravel()
        sims[i] = -1  # исключить сам фильм
        sims[self.c_counts < self.min_content_ratings] = -1  # исключить малоизвестные

        top = np.argsort(-sims)[:limit]
        return _clean(self._fmt(self.c_ids[top], sims[top], "score"))

    def personal(self, user_id: int, ratings: dict = None, limit: int = 10, alpha: float = 0.6):
        if ratings is None: ratings = self.ratings_of(user_id)
        if not ratings:
            return [dict(r, reason="холодный старт: популярное") for r in self.popular(limit)]

        pred, _, strength = self._cf_scores(ratings, exclude_user=user_id)
        strength = np.where(np.isnan(pred), np.nan, strength)

        # обнуляем силу для уже оцененных фильмов
        for m in ratings:
            j = self.m_idx.get(int(m))
            if j is not None: strength[j] = np.nan

        # нормализуем силу коллаборативной части в диапазон 0..1
        smax = np.nanmax(strength) if np.isfinite(strength).any() else 0.0
        cf = np.full(len(self.c_ids), np.nan)
        j_of = np.array([self.m_idx.get(int(m), -1) for m in self.c_ids])
        ok = j_of >= 0
        if smax > 0: cf[ok] = strength[j_of[ok]] / smax

        # формируем профиль вкуса пользователя: средневзвешенный вектор любимых фильмов
        # берем только фильмы с оценкой > 3, вес = оценка - 3
        w = {m: r - 3.0 for m, r in ratings.items() if r > 3 and int(m) in self.c_pos}
        if not w:
            # если нет высоких оценок, берем просто самые последние/высокие
            top = sorted(((r, m) for m, r in ratings.items() if int(m) in self.c_pos), reverse=True)[:5]
            w = {m: 1.0 for _, m in top}

        # суммируем векторы TF-IDF любимых фильмов с весами
        prof = sum(self.X[self.c_pos[int(m)]] * wt for m, wt in w.items())
        # считаем сходство всех фильмов с этим профилем
        cs = np.asarray((self.X @ prof.T).todense()).ravel() if len(w) else np.zeros(len(self.c_ids))
        cs = cs / cs.max() if cs.max() > 0 else cs  # нормализация 0..1

        # финальная формула гибрида
        hybrid = np.where(np.isnan(cf), (1 - alpha) * cs * 0.8, alpha * cf + (1 - alpha) * cs)

        # исключаем оцененные и непопулярные
        for m in ratings:
            if int(m) in self.c_pos: hybrid[self.c_pos[int(m)]] = -1
        hybrid[self.c_counts < self.min_content_ratings] = -1

        top = np.argsort(-hybrid)[:limit]
        out = self._fmt(self.c_ids[top], hybrid[top], "score")
        # добавляем отдельные компоненты скоринга для отладки/объяснения
        out["cf_score"] = np.round(np.where(np.isnan(cf[top]), np.nan, cf[top]), 3)
        out["content_score"] = np.round(cs[top], 3)
        return _clean(out)

    def _title(self, mid):
        return str(self.movies.at[int(mid), "title_ru"]) if int(mid) in self.movies.index else str(mid)

    def explain_user_based(self, user_id: int, movie_id: int, ratings: dict = None, k: int = 50,
                           limit: int = 10, movies_per_user: int = 15):
        movie_id = int(movie_id)
        if ratings is None: ratings = self.ratings_of(user_id)
        j = self.m_idx.get(movie_id)
        nb, S = self._neighbors(ratings, exclude_user=user_id, k=k)

        out = {"movie_id": movie_id, "title_ru": self._title(movie_id), "n_neighbors": int(len(nb)),
               "n_raters": 0, "predicted_rating": None, "neighbors": []}

        if j is None or len(nb) == 0: return out

        mine = {int(m): float(r) for m, r in ratings.items()}  # мои оценки для сравнения
        used = []
        # ищем среди соседей тех, кто оценил этот конкретный фильм
        for ni, sim in zip(nb, S):
            row = self.R[ni]
            their = dict(zip(row.indices, row.data))  # оценки соседа
            if their.get(j, 0) > 0: used.append((ni, float(sim), float(their[j]), their))

        out["n_raters"] = len(used)
        if used:
            # считаем взвешенную среднюю оценку от этих соседей
            w = np.array([u[1] for u in used]);
            r = np.array([u[2] for u in used])
            out["predicted_rating"] = round(float((w * r).sum() / w.sum()), 2)

        # формируем детальный список соседей и их фильмов
        for ni, sim, r_movie, their in used[:limit]:
            items = []
            for jj, rr in their.items():
                mid = int(self.movie_ids[jj])
                # добавляем фильм соседа и мою оценку на него (если есть)
                items.append(
                    {"movie_id": mid, "title_ru": self._title(mid), "rating": float(rr), "your_rating": mine.get(mid)})
            # сортируем: сначала общие фильмы, потом по высокой оценке соседа
            items.sort(key=lambda x: (x["your_rating"] is None, -x["rating"]))

            out["neighbors"].append({
                "user_id": int(self.user_ids[ni]),
                "username": f"Пользователь {int(self.user_ids[ni])}",
                "similarity": round(sim, 3),
                "rating": r_movie,
                "common_movies": sum(1 for x in items if x["your_rating"] is not None),
                "n_rated": len(items),
                "movies": items[:movies_per_user]  # показываем только топ фильмов соседа
            })
        return out

    def explain_item_based(self, base_id: int, rec_id: int, method: str = "cosine", limit: int = 15):

        base_id, rec_id = int(base_id), int(rec_id)
        ja, jb = self.m_idx.get(base_id), self.m_idx.get(rec_id)

        out = {"base_title": self._title(base_id), "rec_title": self._title(rec_id), "similarity": None,
               "n_common": 0, "n_both_liked": 0, "users": []}

        if ja is None or jb is None: return out
        # получаем столбцы оценок для обоих фильмов
        ca, cb = self.R[:, ja].toarray().ravel(), self.R[:, jb].toarray().ravel()
        # находим пользователей, оценивших ОБА фильма
        both = np.where((ca > 0) & (cb > 0))[0]

        out["n_common"] = int(len(both))
        # сколько из них поставили обоим фильмам высокую оценку (>=4)
        out["n_both_liked"] = int(((ca[both] >= 4) & (cb[both] >= 4)).sum())

        M = self.Item_pear if method == "pearson" else self.Item_cos
        if base_id in self.item_pos and rec_id in self.item_pos:
            # вычисляем точное значение сходства из матрицы
            out["similarity"] = round(float((M[self.item_pos[base_id]] @ M[self.item_pos[rec_id]].T).toarray()[0, 0]),
                                      3)

        # сортируем общих пользователей: приоритет тем, кто высоко оценил оба фильма
        order = both[np.argsort(-(np.minimum(ca[both], cb[both]) * 10 + ca[both] + cb[both]))][:limit]

        out["users"] = [{"user_id": int(self.user_ids[u]), "username": f"Пользователь {int(self.user_ids[u])}",
                         "base_rating": float(ca[u]), "rec_rating": float(cb[u])} for u in order]
        return out

    def explain_content(self, base_id: int, rec_id: int):
        if int(base_id) not in self.movies.index or int(rec_id) not in self.movies.index: return None

        # получаем списки токенов для обоих фильмов
        a = list(dict.fromkeys(self._doc(next(self.movies.loc[[int(base_id)]].itertuples()))))
        b = list(dict.fromkeys(self._doc(next(self.movies.loc[[int(rec_id)]].itertuples()))))

        pretty = lambda toks: [t.replace(":", ": ", 1) for t in toks]

        return {"base_title": self._title(base_id), "rec_title": self._title(rec_id),
                "shared": pretty([t for t in a if t in b]),  # общие признаки
                "only_rec": pretty([t for t in b if t not in a])}  # уникальные для рекомендованного