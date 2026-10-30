import threading
import time
from contextlib import asynccontextmanager
from typing import List, Optional

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .config import REFRESH_SECONDS
from .database import engine, get_db
from .models import Movie, Rating, User
from .recommender import RecommenderEngine
from .schemas import (CoRater, ExplainContent, ExplainItemBased, ExplainUserBased, HelpCommand, MovieDetail, MovieItem,
                      NeighborOut, RatingCreate, RatingOut, RatingSaved, UserCreate, UserOut)

MOVIE_SQL = (
    "SELECT id AS movie_id, title_ru, title_orig, year, genres_ru, tags_ru, country_ru, language_ru, director_ru FROM movies")
RATING_SQL = "SELECT user_id, movie_id, rating FROM ratings"


class State:
    engine: Optional[RecommenderEngine] = None
    built_at: float = 0.0
    dirty: bool = False
    lock = threading.Lock()  # защищает от ситуации, когда два запроса одновременно начнут пересобирать модель


def build_engine():
    movies = pd.read_sql_query(text(MOVIE_SQL), engine)
    ratings = pd.read_sql_query(text(RATING_SQL), engine)
    State.engine = RecommenderEngine(movies, ratings)
    State.built_at, State.dirty = time.time(), False


def get_engine() -> RecommenderEngine:
    #один поток
    with State.lock:
        if State.engine is None or (State.dirty and time.time() - State.built_at > REFRESH_SECONDS):
            build_engine()
    return State.engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # при запуске сервера
    build_engine()
    yield  # сервер работает


app = FastAPI(title="API рекомендательной системы фильмов", version="1.0",description="Топ популярных, коллаборативная фильтрация (по фильмам и пользователям), ""рекомендации по содержанию, персональные рекомендации, оценки и отзывы.", lifespan=lifespan)

#параметр запроса для валидации лимита (от 1 до 50, по умолчанию 10)
LIMIT = Query(10, ge=1, le=50, description="Сколько фильмов вернуть (по умолчанию 10)")


@app.get("/health", tags=["Служебные"], summary="Проверка работы API")
def health(db: Session = Depends(get_db)):
    n_movies = db.scalar(select(func.count(Movie.id)))
    n_users = db.scalar(select(func.count(User.id)))
    n_ratings = db.scalar(select(func.count(Rating.id)))
    return {"status": "ok", "movies": n_movies, "users": n_users, "ratings": n_ratings}


@app.post("/admin/reload", tags=["Служебные"], summary="Пересобрать модель по данным из БД")
def reload_model():
    with State.lock:
        build_engine()
    return {"status": "модель пересобрана"}


@app.get("/genres", response_model=List[str], tags=["Фильмы"], summary="Список жанров")
def genres():
    return get_engine().genres()


@app.get("/movies/search", response_model=List[MovieItem], tags=["Фильмы"], summary="Поиск фильма по названию")
def search_movies(q: str = Query(..., min_length=1, description="Часть названия (русского или оригинального)"),
                  limit: int = Query(20, ge=1, le=100)):
    return get_engine().search(q, limit)


@app.get("/movies/popular", response_model=List[MovieItem], tags=["1. Популярные"],
         summary="Топ-10 популярных фильмов (взвешенный рейтинг IMDb)")
def popular(limit: int = LIMIT, genre: Optional[str] = Query(None, description="Фильтр по жанру, напр. «Комедия»"),
            min_year: Optional[int] = Query(None, description="Не старше года выпуска")):
    return get_engine().popular(limit, genre, min_year)


@app.get("/movies/{movie_id}", response_model=MovieDetail, tags=["Фильмы"], summary="Карточка фильма")
def movie_card(movie_id: int):
    res = get_engine().get_movie(movie_id)
    if not res:
        raise HTTPException(404, "Фильм не найден")
    return res


@app.get("/movies/{movie_id}/reviews", response_model=List[RatingOut], tags=["Фильмы"], summary="Отзывы на фильм")
def movie_reviews(movie_id: int, limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    q = (select(Rating, User.username).join(User, User.id == Rating.user_id)
         .where(Rating.movie_id == movie_id,
                Rating.comment.is_not(None))  #
         .order_by(Rating.review_date.desc(), Rating.id.desc()).limit(
        limit))
    return [_rating_out(r, None, uname) for r, uname in db.execute(q).all()]


@app.get("/recommendations/item-based/{movie_id}", response_model=List[MovieItem],
         tags=["2. Коллаборативная фильтрация"],
         summary="Похожие фильмы (по фильмам): тем, кто оценил этот фильм, нравятся также…")
def item_based(movie_id: int, limit: int = LIMIT,
               method: str = Query("cosine", pattern="^(cosine|pearson)$",
                                   description="cosine — косинусное сходство, pearson — корреляция Пирсона")):
    e = get_engine()
    if not e.exists(movie_id):
        raise HTTPException(404, "Фильм не найден")
    return e.item_based(movie_id, limit, method)


@app.get("/recommendations/user-based/{user_id}", response_model=List[MovieItem],
         tags=["2. Коллаборативная фильтрация"],
         summary="Рекомендации по похожим пользователям (по пользователям)")
def user_based(user_id: int, limit: int = LIMIT, db: Session = Depends(get_db)):
    ratings = _user_ratings(db, user_id)
    return get_engine().user_based(user_id, limit, ratings=ratings)


@app.get("/recommendations/content/{movie_id}", response_model=List[MovieItem], tags=["3. По содержанию"],
         summary="Похожие по содержанию (жанры, теги, страна, язык, десятилетие)")
def content_based(movie_id: int, limit: int = LIMIT):
    e = get_engine()
    if not e.exists(movie_id):
        raise HTTPException(404, "Фильм не найден")
    return e.content_based(movie_id, limit)


@app.get("/recommendations/personal/{user_id}", response_model=List[MovieItem], tags=["4. Персональные"],
         summary="Персональные рекомендации для пользователя (гибрид CF + содержание)")
def personal(user_id: int, limit: int = LIMIT,
             alpha: float = Query(0.6, ge=0, le=1, description="Вес коллаборативной части"),
             db: Session = Depends(get_db)):
    ratings = _user_ratings(db, user_id)
    return get_engine().personal(user_id, ratings=ratings, limit=limit, alpha=alpha)


@app.get("/explain/user-based/{user_id}/{movie_id}", response_model=ExplainUserBased, tags=["Объяснение рекомендаций"],
         summary="На основе каких пользователей рекомендован фильм (их оценки и фильмы)")
def explain_user_based(user_id: int, movie_id: int,
                       limit: int = Query(10, ge=1, le=30, description="Сколько похожих пользователей показать"),
                       db: Session = Depends(get_db)):
    e = get_engine()
    if not e.exists(movie_id):
        raise HTTPException(404, "Фильм не найден")
    res = e.explain_user_based(user_id, movie_id, ratings=_user_ratings(db, user_id), limit=limit)
    _apply_usernames(db, res["neighbors"])
    return res


@app.get("/explain/item-based/{movie_id}/{rec_id}", response_model=ExplainItemBased, tags=["Объяснение рекомендаций"],
         summary="Почему фильм rec_id похож на movie_id: кто оценил оба и какие оценки поставил")
def explain_item_based(movie_id: int, rec_id: int, method: str = Query("cosine", pattern="^(cosine|pearson)$"),
                       limit: int = Query(15, ge=1, le=50), db: Session = Depends(get_db)):
    e = get_engine()
    if not (e.exists(movie_id) and e.exists(rec_id)):
        raise HTTPException(404, "Фильм не найден")
    res = e.explain_item_based(movie_id, rec_id, method, limit)
    _apply_usernames(db, res["users"])
    return res


@app.get("/explain/content/{movie_id}/{rec_id}", response_model=ExplainContent, tags=["Объяснение рекомендаций"],
         summary="Какие жанры, теги, страна, язык у двух фильмов совпадают")
def explain_content(movie_id: int, rec_id: int):
    res = get_engine().explain_content(movie_id, rec_id)
    if not res:
        raise HTTPException(404, "Фильм не найден")
    return res


@app.get("/users", response_model=List[UserOut], tags=["Пользователи и оценки"], summary="Список пользователей")
def list_users(limit: int = Query(50, ge=1, le=500), offset: int = 0, db: Session = Depends(get_db)):
    # подзапрос (subquery),
    cnt = select(Rating.user_id, func.count(Rating.id).label("n")).group_by(Rating.user_id).subquery()
    q = (select(User, func.coalesce(cnt.c.n, 0)).outerjoin(cnt, cnt.c.user_id == User.id)  # coalesce заменяет null на 0
         .order_by(User.id).limit(limit).offset(offset))
    return [UserOut(id=u.id, username=u.username, favorite_genre=u.favorite_genre, n_ratings=n) for u, n in
            db.execute(q).all()]


@app.post("/users", response_model=UserOut, status_code=201, tags=["Пользователи и оценки"],
          summary="Создать пользователя")
def create_user(body: UserCreate, db: Session = Depends(get_db)):
    user = User(username=body.username.strip())
    db.add(user)
    db.commit()  # сохраняем в бд
    db.refresh(user)  # получаем объект обратно с присвоенным базой id
    return UserOut(id=user.id, username=user.username, favorite_genre=user.favorite_genre, n_ratings=0)


@app.get("/users/{user_id}", response_model=UserOut, tags=["Пользователи и оценки"], summary="Данные пользователя")
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    n = db.scalar(select(func.count(Rating.id)).where(Rating.user_id == user_id))
    return UserOut(id=user.id, username=user.username, favorite_genre=user.favorite_genre, n_ratings=n)


@app.get("/users/{user_id}/ratings", response_model=List[RatingOut], tags=["Пользователи и оценки"],
         summary="Оценки и отзывы пользователя (сначала новые)")
def user_ratings(user_id: int, limit: int = Query(50, ge=1, le=500), db: Session = Depends(get_db)):
    q = (select(Rating, Movie.title_ru).join(Movie, Movie.id == Rating.movie_id).where(Rating.user_id == user_id)
         .order_by(Rating.review_date.desc(), Rating.id.desc()).limit(limit))
    return [_rating_out(r, title, None) for r, title in db.execute(q).all()]


@app.post("/ratings", response_model=RatingSaved, status_code=201, tags=["Пользователи и оценки"],
          summary="Оценить фильм и (по желанию) оставить отзыв — сохраняется в БД")
def save_rating(body: RatingCreate, db: Session = Depends(get_db)):
    user, movie = db.get(User, body.user_id), db.get(Movie, body.movie_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    if not movie:
        raise HTTPException(404, "Фильм не найден")

    comment = (body.comment or "").strip() or None
    existing = db.scalar(select(Rating).where(Rating.user_id == body.user_id, Rating.movie_id == body.movie_id))
    created = existing is None

    if created:
        existing = Rating(user_id=body.user_id, movie_id=body.movie_id, rating=body.rating, comment=comment,
                          source="app")
        db.add(existing)
    else:
        existing.rating, existing.comment, existing.source = body.rating, comment, "app"
        existing.review_date = func.current_date()

    db.commit()
    db.refresh(existing)
    State.dirty = True

    return RatingSaved(status="сохранено", created=created, rating=_rating_out(existing, movie.title_ru, user.username))


def _user_ratings(db: Session, user_id: int) -> dict:
    if not db.get(User, user_id):
        raise HTTPException(404, "Пользователь не найден")
    rows = db.execute(select(Rating.movie_id, Rating.rating).where(Rating.user_id == user_id)).all()
    return {m: float(r) for m, r in rows}


def _apply_usernames(db: Session, rows: list):
    ids = [r["user_id"] for r in rows]
    if not ids:
        return
    names = dict(db.execute(select(User.id, User.username).where(User.id.in_(ids))).all())
    for r in rows:
        r["username"] = names.get(r["user_id"], r["username"])


def _rating_out(r: Rating, title: Optional[str], username: Optional[str]) -> RatingOut:
    return RatingOut(user_id=r.user_id, movie_id=r.movie_id, title_ru=title, username=username, rating=r.rating,
                     comment=r.comment, review_date=str(r.review_date) if r.review_date else None)